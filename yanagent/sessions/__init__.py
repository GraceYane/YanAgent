"""对话持久化相关接口。"""

from .desktop import DesktopSessionService
from .store import MessagePage, SessionPage, SessionRecord, SessionStore, StoredMessage

__all__ = [
    "DesktopSessionService",
    "MessagePage",
    "SessionPage",
    "SessionRecord",
    "SessionStore",
    "StoredMessage",
]
