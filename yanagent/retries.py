"""模型请求的有限退避策略；重试范围不包含工具执行或整个 Agent Run。"""

from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from yanagent.errors import AgentError, EmptyModelResponseError, ModelServerError, RateLimitError


def parse_retry_after(value: str | None) -> float | None:
    """解析服务端秒数或 HTTP 日期提示；非法值忽略，超长等待交给总期限处理。"""
    if not value or len(value) > 128:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            seconds = (target - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


def retry_delay(error: AgentError, retry_index: int) -> float | None:
    """空响应最多补一次；限流与 5xx 最多补两次，使用带抖动的指数退避。"""
    if isinstance(error, EmptyModelResponseError):
        return 0.0 if retry_index == 0 else None
    if not isinstance(error, (RateLimitError, ModelServerError)) or retry_index >= 2:
        return None
    delay = min(30.0, 2.0 ** retry_index + random.uniform(0.0, 0.25))
    return max(delay, error.retry_after_seconds or 0.0)
