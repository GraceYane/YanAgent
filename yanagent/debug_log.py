"""YanAgent 临时流程调试日志：统一格式化，并可独占控制台输出。"""

from __future__ import annotations

import logging
import os
import sys
from pprint import pformat
from typing import Any


DEBUG_LOGGER_NAME = "yanagent.debug_trace"
DEBUG_ONLY_ENV = "YANAGENT_DEBUG_ONLY"
_LOGGER = logging.getLogger(DEBUG_LOGGER_NAME)


class _SuppressRegularLogFilter(logging.Filter):
    """调试独占模式下拦截根处理器收到的所有普通日志。"""

    def filter(self, _record: logging.LogRecord) -> bool:
        """返回 False，防止普通日志写入当前根处理器。"""
        return False


_SUPPRESS_FILTER = _SuppressRegularLogFilter()


def _enabled_from_env() -> bool:
    """判断环境变量是否要求只显示 yan_debug 日志。"""
    value = os.environ.get(DEBUG_ONLY_ENV, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def configure_yan_debug_logging(*, only_debug: bool | None = None) -> bool:
    """配置调试日志；独占模式隐藏普通日志，只输出 ``yan_debug`` 内容。"""
    selected = _enabled_from_env() if only_debug is None else only_debug
    root = logging.getLogger()

    for handler in root.handlers:
        handler.removeFilter(_SUPPRESS_FILTER)

    for handler in list(_LOGGER.handlers):
        if getattr(handler, "_yan_debug_handler", False):
            _LOGGER.removeHandler(handler)
            handler.close()

    if not selected:
        _LOGGER.propagate = True
        return False

    for handler in root.handlers:
        handler.addFilter(_SUPPRESS_FILTER)

    debug_handler = logging.StreamHandler(sys.stdout)
    debug_handler._yan_debug_handler = True  # type: ignore[attr-defined]
    debug_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _LOGGER.handlers.clear()
    _LOGGER.addHandler(debug_handler)
    _LOGGER.setLevel(logging.INFO)
    _LOGGER.propagate = False
    return True


def yan_debug(source: str, function: str, message: str, /, **values: Any) -> None:
    """输出一条统一的流程调试日志，并对附加对象执行多行美化。"""
    lines = [f"[yanDebug][{source}][{function}] {message}"]
    for name, value in values.items():
        lines.append(f"{name}:\n{pformat(value, sort_dicts=False, width=120)}")
    _LOGGER.info("\n".join(lines))
