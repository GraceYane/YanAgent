"""对话持久化相关接口。"""

from .desktop import DesktopSessionService
from .runs import RunStore, StoredRun
from .store import MessagePage, SessionPage, SessionRecord, SessionStore, StoredMessage

__all__ = [
    "DesktopSessionService",
    "MessagePage",
    "RunStore",
    "SessionPage",
    "SessionRecord",
    "SessionStore",
    "StoredMessage",
    "StoredRun",
]
