"""trycatchslot — decorator for safe Qt slot execution."""
from __future__ import annotations

import functools
import inspect
import logging
from typing import Any, Callable, TypeVar, cast

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def trycatchslot(func: F) -> F:
    """Wrap a Qt slot: log and call show_error or emit error on exception."""

    @functools.wraps(func)
    def wrapper(self: Any, *args: Any) -> Any:
        sig = inspect.signature(func)
        trimmed_args = args[: (len(sig.parameters) - 1)]
        result: Any = None
        try:
            result = func(self, *trimmed_args)
        except Exception as ex:
            logger.exception(ex)
            if hasattr(self, "show_error"):
                self.show_error(ex)
            elif hasattr(self, "error"):
                self.error.emit(ex)
            else:
                logger.warning("Error class %s has no member show_error or error", self)
        return result

    return cast(F, wrapper)
