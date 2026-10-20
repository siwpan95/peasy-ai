"""
会话管理器：多轮对话上下文追踪。

特性：
- session_id 隔离的对话历史
- 最近 N 轮对话记忆
- 当前话题追踪
- 用户偏好记录
- 超时自动清理

用法：
    sm = SessionManager(max_history=10, ttl_minutes=30)
    session = sm.get_or_create("user_123")

    # 记录一轮对话
    sm.record("user_123", "你好", "你好呀！")

    # 获取上下文
    ctx = sm.get_context("user_123")
    print(ctx["last_topic"])
"""

import time
import re
from collections import deque
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class Turn:
    """一轮对话。"""
    user_input: str
    bot_reply: str
    timestamp: float = field(default_factory=time.time)

    @property
    def age_seconds(self) -> float:
        return time.time() - self.timestamp


class SessionManager:
    """管理多个用户会话的对话上下文。"""

    def __init__(self, max_history: int = 10, ttl_minutes: int = 30):
        """
        Args:
            max_history: 每个 session 保留的最近对话轮数。
            ttl_minutes: session 闲置超时分钟数，超时自动清理。
        """
        self.max_history = max_history
        self.ttl_seconds = ttl_minutes * 60
        self._sessions: Dict[str, Dict[str, Any]] = {}

    # ============================================================
    # Session 管理
    # ============================================================
    def get_or_create(self, session_id: str) -> Dict[str, Any]:
        """获取或创建会话。"""
        self._cleanup()
        if session_id not in self._sessions:
            self._sessions[session_id] = {
                "history": deque(maxlen=self.max_history),
                "user_name": "",
                "user_prefs": {},
                "last_topic": "",
                "topic_streak": 0,
                "total_turns": 0,
                "created_at": time.time(),
                "last_active": time.time(),
            }
        self._sessions[session_id]["last_active"] = time.time()
        return self._sessions[session_id]

    def exists(self, session_id: str) -> bool:
        return session_id in self._sessions

    def remove(self, session_id: str):
        self._sessions.pop(session_id, None)

    def clear_all(self):
        self._sessions.clear()

    # ============================================================
    # 对话记录
    # ============================================================
    def record(self, session_id: str, user_input: str, bot_reply: str):
        """记录一轮对话。"""
        session = self.get_or_create(session_id)
        turn = Turn(user_input=user_input, bot_reply=bot_reply)
        session["history"].append(turn)
        session["total_turns"] += 1

        # 更新话题追踪
        self._update_topic(session, user_input)

    def _update_topic(self, session: Dict, text: str):
        """简单的话题跟踪。"""
        # 尝试提取话题关键词
        keywords = re.findall(r'[\u4e00-\u9fa5]{2,}', text)
        if keywords:
            topic = keywords[0]
            if topic == session.get("last_topic"):
                session["topic_streak"] += 1
            else:
                session["last_topic"] = topic
                session["topic_streak"] = 1

    # ============================================================
    # 上下文获取
    # ============================================================
    def get_context(self, session_id: str) -> Dict[str, Any]:
        """获取会话上下文（注入到匹配过程中）。"""
        session = self.get_or_create(session_id)
        return {
            "user_name": session.get("user_name", ""),
            "last_topic": session.get("last_topic", ""),
            "topic_streak": session.get("topic_streak", 0),
            "total_turns": session.get("total_turns", 0),
            "recent_history": list(session["history"])[-3:],  # 最近 3 轮
        }

    def get_history(self, session_id: str, n: int = 5) -> List[Turn]:
        """获取最近 n 轮对话记录。"""
        session = self.get_or_create(session_id)
        return list(session["history"])[-n:]

    def get_last(self, session_id: str) -> Optional[Turn]:
        """获取上一轮对话。"""
        session = self.get_or_create(session_id)
        history = session["history"]
        return history[-1] if history else None

    # ============================================================
    # 用户信息
    # ============================================================
    def set_user_name(self, session_id: str, name: str):
        self.get_or_create(session_id)["user_name"] = name

    def get_user_name(self, session_id: str) -> str:
        return self.get_or_create(session_id).get("user_name", "")

    def set_pref(self, session_id: str, key: str, value: Any):
        self.get_or_create(session_id)["user_prefs"][key] = value

    def get_pref(self, session_id: str, key: str, default=None):
        return self.get_or_create(session_id)["user_prefs"].get(key, default)

    # ============================================================
    # 内部清理
    # ============================================================
    def _cleanup(self):
        """清理超时 session。"""
        now = time.time()
        expired = [
            sid for sid, s in self._sessions.items()
            if now - s.get("last_active", 0) > self.ttl_seconds
        ]
        for sid in expired:
            del self._sessions[sid]

    # ============================================================
    # 信息
    # ============================================================
    @property
    def session_count(self) -> int:
        return len(self._sessions)

    def total_turns_all(self) -> int:
        return sum(s.get("total_turns", 0) for s in self._sessions.values())

    def __repr__(self):
        return f"<SessionManager sessions={self.session_count} max_history={self.max_history}>"
