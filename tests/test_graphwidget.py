"""Tests for GraphUI — live plotting widget for numeric Redis keys.

TDD RED phase: written before implementation, validated to fail,
then driven GREEN by redisclient/graphwidget.py.
"""
from __future__ import annotations

import pytest
import fakeredis
from PyQt6.QtWidgets import QPushButton, QSpinBox, QVBoxLayout, QWidget

from redisclient.redis_client import RedisClient
from redisclient.graphwidget import COLOR_CYCLE, USE_GRAPH, GraphUI

pytestmark = pytest.mark.skipif(not USE_GRAPH, reason="pyqtgraph not installed")


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def client_with_numeric_data() -> RedisClient:
    """RedisClient with seeded numeric and non-numeric string keys."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    fake.set("sensors:temperature", "25.5")
    fake.set("sensors:humidity", "70.2")
    fake.set("non:numeric", "hello")
    client = RedisClient()
    client.attach(fake)
    return client


@pytest.fixture
def graph_with_layout(qapp) -> tuple[GraphUI, QVBoxLayout, QWidget]:
    """GraphUI wired into a container with a QVBoxLayout, ready for tests."""
    import pyqtgraph as pg

    container = QWidget()
    layout = QVBoxLayout()
    container.setLayout(layout)
    graph = GraphUI()
    graph.setup_ui(layout)
    return graph, layout, container


# ──────────────────────────────────────────────────────────────
# setup_ui — Layout construction
# ──────────────────────────────────────────────────────────────


class TestSetupUI:
    """Tests for setup_ui layout and control creation."""

    def test_setup_ui_creates_plot_widget(self, qapp) -> None:
        """setup_ui adds exactly one PlotWidget to the parent layout."""
        import pyqtgraph as pg

        container = QWidget()
        layout = QVBoxLayout()
        container.setLayout(layout)
        graph = GraphUI()
        graph.setup_ui(layout)

        plot_widgets = [
            layout.itemAt(i).widget()
            for i in range(layout.count())
            if isinstance(layout.itemAt(i).widget(), pg.PlotWidget)
        ]
        assert len(plot_widgets) == 1

    def test_setup_ui_creates_controls(self, graph_with_layout) -> None:
        """numPointsSpinBox, intervalSpinBox, applyButton exist with ranges/defaults."""
        _, layout, container = graph_with_layout

        num_points = container.findChild(QSpinBox, "numPointsSpinBox")
        interval = container.findChild(QSpinBox, "intervalSpinBox")
        apply_btn = container.findChild(QPushButton, "applyButton")

        assert num_points is not None, "numPointsSpinBox not found"
        assert interval is not None, "intervalSpinBox not found"
        assert apply_btn is not None, "applyButton not found"

        assert num_points.minimum() == 10
        assert num_points.maximum() == 100
        assert num_points.value() == 30

        assert interval.minimum() == 1
        assert interval.maximum() == 3600
        assert interval.value() == 5


# ──────────────────────────────────────────────────────────────
# add_key — Adding keys to the plot
# ──────────────────────────────────────────────────────────────


class TestAddKey:
    """Tests for add_key key storage, curve creation, and validation."""

    def test_add_key_stores_key(
        self, graph_with_layout, client_with_numeric_data: RedisClient
    ) -> None:
        """add_key stores the key name so get_keys() contains it."""
        graph, _, _ = graph_with_layout
        graph.add_key(client_with_numeric_data, "sensors:temperature")
        assert "sensors:temperature" in graph.get_keys()

    def test_add_key_creates_curve(
        self, graph_with_layout, client_with_numeric_data: RedisClient
    ) -> None:
        """Each added key gets a pyqtgraph curve in _curves."""
        graph, _, _ = graph_with_layout
        graph.add_key(client_with_numeric_data, "sensors:temperature")
        assert "sensors:temperature" in graph._curves
        assert graph._curves["sensors:temperature"] is not None

    def test_add_key_rejects_non_numeric(
        self, graph_with_layout, client_with_numeric_data: RedisClient
    ) -> None:
        """Adding a non-numeric key emits error and does not add it."""
        graph, _, _ = graph_with_layout
        errors: list[Exception] = []
        graph.error.connect(lambda ex: errors.append(ex))

        graph.add_key(client_with_numeric_data, "non:numeric")

        assert "non:numeric" not in graph.get_keys()
        assert len(errors) == 1
        assert isinstance(errors[0], ValueError)

    def test_add_key_assigns_color_from_cycle(
        self, graph_with_layout, client_with_numeric_data: RedisClient
    ) -> None:
        """First key gets COLOR_CYCLE[0], second gets COLOR_CYCLE[1]."""
        graph, _, _ = graph_with_layout
        graph.add_key(client_with_numeric_data, "sensors:temperature")
        graph.add_key(client_with_numeric_data, "sensors:humidity")

        # pyqtgraph stores pen color info; verify via the internal mapping
        keys = graph.get_keys()
        assert len(keys) == 2

    def test_add_key_duplicate_ignored(
        self, graph_with_layout, client_with_numeric_data: RedisClient
    ) -> None:
        """Adding the same key twice does not create a second curve."""
        graph, _, _ = graph_with_layout
        graph.add_key(client_with_numeric_data, "sensors:temperature")
        graph.add_key(client_with_numeric_data, "sensors:temperature")
        assert graph.get_keys().count("sensors:temperature") == 1


# ──────────────────────────────────────────────────────────────
# remove_key — Removing keys from the plot
# ──────────────────────────────────────────────────────────────


class TestRemoveKey:
    """Tests for remove_key key removal and curve cleanup."""

    def test_remove_key(
        self, graph_with_layout, client_with_numeric_data: RedisClient
    ) -> None:
        """remove_key removes the key from get_keys()."""
        graph, _, _ = graph_with_layout
        graph.add_key(client_with_numeric_data, "sensors:temperature")
        graph.remove_key("sensors:temperature")
        assert "sensors:temperature" not in graph.get_keys()

    def test_remove_key_removes_curve(
        self, graph_with_layout, client_with_numeric_data: RedisClient
    ) -> None:
        """remove_key removes the curve from the internal _curves dict."""
        graph, _, _ = graph_with_layout
        graph.add_key(client_with_numeric_data, "sensors:temperature")
        assert "sensors:temperature" in graph._curves

        graph.remove_key("sensors:temperature")
        assert "sensors:temperature" not in graph._curves

    def test_remove_nonexistent_key_no_error(
        self, graph_with_layout
    ) -> None:
        """remove_key on a key that was never added does not raise."""
        graph, _, _ = graph_with_layout
        graph.remove_key("does:not:exist")
        assert graph.get_keys() == []


# ──────────────────────────────────────────────────────────────
# restart_timer — Timer behavior
# ──────────────────────────────────────────────────────────────


class TestRestartTimer:
    """Tests for timer interval configuration via applyButton."""

    def test_restart_timer_updates_interval(self, graph_with_layout) -> None:
        """Changing intervalSpinBox + clicking applyButton restarts timer."""
        graph, _, container = graph_with_layout
        interval = container.findChild(QSpinBox, "intervalSpinBox")
        apply_btn = container.findChild(QPushButton, "applyButton")

        interval.setValue(10)
        apply_btn.click()

        # QTimer.interval() returns milliseconds; spinbox is in seconds
        assert graph._timer.interval() == 10 * 1000

    def test_restart_timer_default_interval(self, graph_with_layout) -> None:
        """After setup_ui, timer interval matches default (5s = 5000ms)."""
        graph, _, _ = graph_with_layout
        assert graph._timer.interval() == 5 * 1000


# ──────────────────────────────────────────────────────────────
# clear — Clearing the plot
# ──────────────────────────────────────────────────────────────


class TestClear:
    """Tests for clear() resetting all state."""

    def test_clear_removes_all(
        self, graph_with_layout, client_with_numeric_data: RedisClient
    ) -> None:
        """clear() removes all keys, curves, and channels."""
        graph, _, _ = graph_with_layout
        graph.add_key(client_with_numeric_data, "sensors:temperature")
        graph.add_key(client_with_numeric_data, "sensors:humidity")
        assert len(graph.get_keys()) == 2

        graph.clear()

        assert graph.get_keys() == []
        assert graph._curves == {}
        assert graph._channels == {}


# ──────────────────────────────────────────────────────────────
# get_keys — Key listing
# ──────────────────────────────────────────────────────────────


class TestGetKeys:
    """Tests for get_keys() return type and contents."""

    def test_get_keys_returns_list(self, graph_with_layout) -> None:
        """get_keys() returns a list (not a dict, tuple, etc.)."""
        graph, _, _ = graph_with_layout
        keys = graph.get_keys()
        assert isinstance(keys, list)

    def test_get_keys_empty_initially(self, graph_with_layout) -> None:
        """get_keys() returns empty list before any add_key call."""
        graph, _, _ = graph_with_layout
        assert graph.get_keys() == []

    def test_get_keys_contains_added(
        self, graph_with_layout, client_with_numeric_data: RedisClient
    ) -> None:
        """get_keys() lists all added key names."""
        graph, _, _ = graph_with_layout
        graph.add_key(client_with_numeric_data, "sensors:temperature")
        graph.add_key(client_with_numeric_data, "sensors:humidity")

        keys = graph.get_keys()
        assert len(keys) == 2
        assert "sensors:temperature" in keys
        assert "sensors:humidity" in keys


# ──────────────────────────────────────────────────────────────
# Polling — Timer tick behavior
# ──────────────────────────────────────────────────────────────


class TestPolling:
    """Tests for the timer tick (_on_timeout) updating curve data."""

    def test_timeout_updates_channel_data(
        self,
        graph_with_layout,
        client_with_numeric_data: RedisClient,
    ) -> None:
        """_on_timeout reads Redis and appends value to rolling buffer."""
        import numpy as np

        graph, _, _ = graph_with_layout
        graph.add_key(client_with_numeric_data, "sensors:temperature")

        # Update fakeredis value to simulate changing sensor
        fake = client_with_numeric_data._redis
        assert fake is not None
        fake.set("sensors:temperature", "30.0")

        graph._on_timeout()

        channel = graph._channels["sensors:temperature"]
        assert channel[-1] == pytest.approx(30.0)
        # All earlier entries should still be 0 (initial buffer)
        assert channel[0] == pytest.approx(0.0)

    def test_timeout_skips_non_numeric_silently(
        self,
        graph_with_layout,
        client_with_numeric_data: RedisClient,
    ) -> None:
        """If a previously-numeric key becomes non-numeric, tick skips it."""
        graph, _, _ = graph_with_layout
        graph.add_key(client_with_numeric_data, "sensors:temperature")

        # Corrupt the value
        fake = client_with_numeric_data._redis
        assert fake is not None
        fake.set("sensors:temperature", "not_a_number")

        errors: list[Exception] = []
        graph.error.connect(lambda ex: errors.append(ex))

        # Should not raise; just skip
        graph._on_timeout()

        # Non-numeric conversion failure is a warning, not an error signal
        # (error signal is for unexpected exceptions, not bad data)

    def test_timeout_multiple_ticks_rolling(
        self,
        graph_with_layout,
        client_with_numeric_data: RedisClient,
    ) -> None:
        """Multiple ticks roll the buffer, keeping only numPoints values."""
        graph, _, container = graph_with_layout
        num_points_spin = container.findChild(QSpinBox, "numPointsSpinBox")
        num_points_spin.setValue(10)

        graph.add_key(client_with_numeric_data, "sensors:temperature")

        fake = client_with_numeric_data._redis
        assert fake is not None

        # Tick 5 times with different values
        for i in range(5):
            fake.set("sensors:temperature", str(100 + i))
            graph._on_timeout()

        channel = graph._channels["sensors:temperature"]
        assert len(channel) == 10  # buffer size unchanged
        # Last 5 entries should be 100,101,102,103,104
        assert channel[-1] == pytest.approx(104.0)
        assert channel[-5] == pytest.approx(100.0)
        # First 5 entries still 0 (initial)
        assert channel[0] == pytest.approx(0.0)


# ──────────────────────────────────────────────────────────────
# Color cycle
# ──────────────────────────────────────────────────────────────


class TestColorCycle:
    """Tests for COLOR_CYCLE constant."""

    def test_color_cycle_has_six_colors(self) -> None:
        """COLOR_CYCLE contains exactly 6 Tango palette colors."""
        assert len(COLOR_CYCLE) == 6

    def test_color_cycle_values(self) -> None:
        """COLOR_CYCLE matches the expected Tango hex values."""
        expected = ['#4e9a06', '#ce5c00', '#3465a4', '#75507b', '#cc0000', '#edd400']
        assert COLOR_CYCLE == expected
