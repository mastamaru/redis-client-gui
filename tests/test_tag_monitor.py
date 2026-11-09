"""Tests for TagMonitorUI — hash field polling."""
from __future__ import annotations

import pytest
import fakeredis
from PyQt6.QtCore import QModelIndex
from PyQt6.QtGui import QStandardItemModel

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


class TestTagMonitorSelection:
    @pytest.mark.parametrize("column", range(4))
    def test_selects_tag_from_each_column_without_mutation(self, qapp, client_with_tags, column):
        ui = TagMonitorUI()
        ui.set_client(client_with_tags)
        ui.add_tag("A107JA_RUN")
        selected = []
        ui.tag_selected.connect(lambda name, tag_type: selected.append((name, tag_type)))
        before = client_with_tags._redis.hgetall("ots-pim:tags")

        ui.select_tag(ui.model.index(0, column))

        assert selected == [("A107JA_RUN", "bool")]
        assert ui.get_monitored_tags() == ["A107JA_RUN"]
        assert client_with_tags._redis.hgetall("ots-pim:tags") == before

    def test_missing_type_defaults_to_float(self, qapp, client_with_tags):
        ui = TagMonitorUI()
        ui.set_client(client_with_tags)
        ui.add_tag("unknown")
        selected = []
        ui.tag_selected.connect(lambda name, tag_type: selected.append((name, tag_type)))

        ui.select_tag(ui.model.index(0, 2))

        assert selected == [("unknown", "float")]

    def test_invalid_foreign_and_removed_indexes_do_not_emit(self, qapp, client_with_tags):
        ui = TagMonitorUI()
        ui.set_client(client_with_tags)
        ui.add_tag("A107JA_RUN")
        removed = ui.model.index(0, 0)
        foreign_model = QStandardItemModel(1, 1)
        selected = []
        ui.tag_selected.connect(lambda name, tag_type: selected.append((name, tag_type)))
        ui.remove_tag("A107JA_RUN")

        for index in (QModelIndex(), foreign_model.index(0, 0), removed):
            ui.select_tag(index)

        assert selected == []

    def test_selection_after_removing_another_row(self, qapp, client_with_tags):
        ui = TagMonitorUI()
        ui.set_client(client_with_tags)
        ui.add_tag("LIC1003A_PV")
        ui.add_tag("SimStatus")
        ui.remove_tag("LIC1003A_PV")
        selected = []
        ui.tag_selected.connect(lambda name, tag_type: selected.append((name, tag_type)))

        ui.select_tag(ui.model.index(0, 3))

        assert selected == [("SimStatus", "string")]
        assert ui.get_monitored_tags() == ["SimStatus"]

    def test_no_client_does_not_emit(self, qapp):
        ui = TagMonitorUI()
        ui.add_tag("unknown")
        selected = []
        ui.tag_selected.connect(lambda name, tag_type: selected.append((name, tag_type)))

        ui.select_tag(ui.model.index(0, 0))

        assert selected == []


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
        assert ui.model.item(0, 1).text() == "1"

    def test_poll_updates_bool_off(self, qapp, client_with_tags):
        ui = TagMonitorUI()
        ui.set_client(client_with_tags)
        ui.add_tag("XV1220A")
        ui._poll()
        assert ui.model.item(0, 1).text() == "0"

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
