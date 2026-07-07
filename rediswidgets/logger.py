"""QtHandler — logging handler that appends messages to a QTextEdit."""
from __future__ import annotations

import logging

from PyQt6.QtWidgets import QTextEdit


class QtHandler(logging.Handler):
    """Logging handler that writes to a QTextEdit widget."""

    def __init__(self, widget: QTextEdit) -> None:
        logging.Handler.__init__(self)
        self.setFormatter(logging.Formatter("%(name)s - %(levelname)s - %(message)s"))
        self.widget = widget

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self.widget.append(msg)
