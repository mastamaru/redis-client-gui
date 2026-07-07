"""GraphUI — live plotting widget for numeric Redis keys.

Polls Redis string keys at a configurable interval and plots them as
real-time rolling-window time series using pyqtgraph.

Adapted from the opcua-client-gui GraphUI class.

When pyqtgraph is not installed, setup_ui inserts a placeholder QLabel
instead of a PlotWidget, so the rest of the application remains usable.
"""
from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from redisclient.redis_client import RedisClient

try:
    import pyqtgraph as pg
    import numpy as np

    USE_GRAPH = True
except ImportError:
    USE_GRAPH = False

logger = logging.getLogger(__name__)

# Tango palette — each new key gets the next color, cycling after 6
COLOR_CYCLE = ['#4e9a06', '#ce5c00', '#3465a4', '#75507b', '#cc0000', '#edd400']

# Defaults for the spin-boxes
DEFAULT_NUM_POINTS = 30
DEFAULT_INTERVAL_SECONDS = 5


class GraphUI(QObject):
    """Live plotting widget for numeric Redis keys.

    Usage::

        graph = GraphUI()
        graph.setup_ui(layout)
        graph.add_key(client, "sensors:temperature")

    A QTimer polls each registered key every *interval* seconds via
    ``client.get_value(key)``.  Values are converted to ``float``; keys
    whose value cannot be converted are skipped on read and cause
    ``error`` to be emitted when first added via :meth:`add_key`.
    """

    error = pyqtSignal(Exception)

    # ──────────────────────────────────────────────
    # Construction
    # ──────────────────────────────────────────────

    def __init__(self) -> None:
        QObject.__init__(self)

        # Ordered list of plotted key names
        self._keys: list[str] = []

        # key_name → pyqtgraph PlotDataItem (curve)
        self._curves: dict[str, Any] = {}

        # key_name → rolling numpy buffer of float values
        self._channels: dict[str, Any] = {}

        # Latest client used by add_key (timer reads through it)
        self._client: RedisClient | None = None

        # PlotWidget created in setup_ui (None until then)
        self._plot_widget: Any = None

        # Polling timer
        self._timer: QTimer = QTimer()
        self._timer.timeout.connect(self._on_timeout)

        # Control widgets (created in setup_ui)
        self._num_points_spin: QSpinBox | None = None
        self._interval_spin: QSpinBox | None = None

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    def setup_ui(self, parent_layout: QVBoxLayout) -> None:
        """Create the PlotWidget and control strip, add to *parent_layout*."""
        if not USE_GRAPH:
            placeholder = QLabel("pyqtgraph not installed")
            parent_layout.addWidget(placeholder)
            return

        # ── Plot widget ──────────────────────────
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.showGrid(x=True, y=True)
        self._plot_widget.addLegend()
        parent_layout.addWidget(self._plot_widget)

        # ── Controls row ─────────────────────────
        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)

        controls_layout.addWidget(QLabel("Points:"))
        self._num_points_spin = QSpinBox()
        self._num_points_spin.setObjectName("numPointsSpinBox")
        self._num_points_spin.setMinimum(10)
        self._num_points_spin.setMaximum(100)
        self._num_points_spin.setValue(DEFAULT_NUM_POINTS)
        controls_layout.addWidget(self._num_points_spin)

        controls_layout.addWidget(QLabel("Interval (s):"))
        self._interval_spin = QSpinBox()
        self._interval_spin.setObjectName("intervalSpinBox")
        self._interval_spin.setMinimum(1)
        self._interval_spin.setMaximum(3600)
        self._interval_spin.setValue(DEFAULT_INTERVAL_SECONDS)
        controls_layout.addWidget(self._interval_spin)

        apply_button = QPushButton("Apply")
        apply_button.setObjectName("applyButton")
        apply_button.clicked.connect(self.restart_timer)
        controls_layout.addWidget(apply_button)

        controls_layout.addStretch()
        parent_layout.addWidget(controls)

        # Start the timer with the default interval
        self.restart_timer()

    def add_key(self, client: RedisClient, key_name: str) -> None:
        """Add a numeric Redis key to the graph.

        Validates immediately that the key's current value is convertible
        to ``float``.  If it is not, :attr:`error` is emitted with a
        ``ValueError`` and the key is not added.
        """
        if not USE_GRAPH or self._plot_widget is None:
            return

        # Ignore duplicates
        if key_name in self._keys:
            logger.debug("Key %s already plotted, ignoring", key_name)
            return

        # Validate numeric value before allocating buffers/curves
        try:
            raw_value = client.get_value(key_name)
            float(raw_value)
        except (ValueError, TypeError) as ex:
            logger.warning("Key %s is not numeric: %s", key_name, ex)
            self.error.emit(ValueError(f"Key '{key_name}' is not numeric"))
            return
        except Exception as ex:
            logger.warning("Failed to read key %s: %s", key_name, ex)
            self.error.emit(ex)
            return

        # Store the client for the timer callback
        self._client = client

        # Allocate the rolling buffer (filled with zeros)
        num_points = DEFAULT_NUM_POINTS
        if self._num_points_spin is not None:
            num_points = self._num_points_spin.value()
        self._channels[key_name] = np.zeros(num_points, dtype=float)

        # Create the curve with the next color from the cycle
        color = COLOR_CYCLE[len(self._keys) % len(COLOR_CYCLE)]
        plot_item = self._plot_widget.getPlotItem()
        curve = plot_item.plot(pen=color, name=key_name)
        self._curves[key_name] = curve
        self._keys.append(key_name)

        logger.info("Added key %s to graph (color=%s)", key_name, color)

    def remove_key(self, key_name: str) -> None:
        """Remove *key_name* and its curve from the graph."""
        if key_name not in self._keys:
            return

        self._keys.remove(key_name)

        curve = self._curves.pop(key_name, None)
        if curve is not None and self._plot_widget is not None:
            try:
                self._plot_widget.getPlotItem().removeItem(curve)
            except Exception:
                logger.exception("Failed to remove curve for %s", key_name)

        self._channels.pop(key_name, None)
        logger.info("Removed key %s from graph", key_name)

    def get_keys(self) -> list[str]:
        """Return a copy of the list of plotted key names."""
        return list(self._keys)

    def restart_timer(self) -> None:
        """Restart the polling timer using the current interval-spin value."""
        if self._interval_spin is None:
            return

        interval_ms = self._interval_spin.value() * 1000
        self._timer.stop()
        self._timer.start(interval_ms)
        logger.debug("Timer restarted: %d ms", interval_ms)

    def clear(self) -> None:
        """Remove all keys, curves, and buffers; leave the plot empty."""
        if self._plot_widget is not None:
            plot_item = self._plot_widget.getPlotItem()
            for curve in list(self._curves.values()):
                try:
                    plot_item.removeItem(curve)
                except Exception:
                    logger.exception("Failed to remove curve during clear()")

        self._keys.clear()
        self._curves.clear()
        self._channels.clear()
        logger.info("Graph cleared")

    # ──────────────────────────────────────────────
    # Internal — timer callback
    # ──────────────────────────────────────────────

    def _on_timeout(self) -> None:
        """Called on each timer tick; reads each key and updates its curve."""
        if self._client is None:
            return

        for key_name in list(self._keys):
            try:
                raw_value = self._client.get_value(key_name)
                value = float(raw_value)
            except (ValueError, TypeError):
                logger.warning(
                    "Could not convert key %s value %r to float; skipping",
                    key_name,
                    raw_value,
                )
                continue
            except Exception as ex:
                logger.warning("Error reading key %s: %s", key_name, ex)
                self.error.emit(ex)
                continue

            channel = self._channels.get(key_name)
            if channel is None:
                continue

            # Roll left and append the new value at the end
            channel = np.roll(channel, -1)
            channel[-1] = value
            self._channels[key_name] = channel

            curve = self._curves.get(key_name)
            if curve is not None:
                curve.setData(channel)
