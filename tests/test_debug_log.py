"""专用流程调试日志的格式化与独占输出测试。"""

from __future__ import annotations

import io
import logging
import unittest
from contextlib import redirect_stdout

from yanagent.debug_log import (
    DEBUG_LOGGER_NAME,
    configure_yan_debug_logging,
    yan_debug,
)


class YanDebugLogTests(unittest.TestCase):
    """验证调试独占模式不会混入普通运行日志。"""

    def test_only_yan_debug_output_remains(self) -> None:
        """根日志被屏蔽，但专用函数仍输出来源、函数和格式化对象。"""
        root = logging.getLogger()
        debug_logger = logging.getLogger(DEBUG_LOGGER_NAME)
        original_root_handlers = list(root.handlers)
        original_root_level = root.level
        original_debug_handlers = list(debug_logger.handlers)
        original_debug_level = debug_logger.level
        original_debug_propagate = debug_logger.propagate
        root.handlers = [logging.StreamHandler(io.StringIO())]
        root.setLevel(logging.INFO)

        captured = io.StringIO()
        try:
            with redirect_stdout(captured):
                self.assertTrue(configure_yan_debug_logging(only_debug=True))
                logging.getLogger("yanagent.ordinary").info("不应出现的普通日志")
                yan_debug(
                    "test_debug_log.py",
                    "test_only_yan_debug_output_remains",
                    "应保留的专用日志",
                    result={"ok": True},
                )
        finally:
            for handler in list(debug_logger.handlers):
                if handler not in original_debug_handlers:
                    debug_logger.removeHandler(handler)
                    handler.close()
            debug_logger.handlers = original_debug_handlers
            debug_logger.setLevel(original_debug_level)
            debug_logger.propagate = original_debug_propagate
            root.handlers = original_root_handlers
            root.setLevel(original_root_level)

        output = captured.getvalue()
        self.assertNotIn("不应出现的普通日志", output)
        self.assertIn("[yanDebug][test_debug_log.py][test_only_yan_debug_output_remains]", output)
        self.assertIn("应保留的专用日志", output)
        self.assertIn("'ok': True", output)


if __name__ == "__main__":
    unittest.main()
