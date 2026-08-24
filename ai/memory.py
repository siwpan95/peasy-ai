"""
动态记忆库：支持学习/遗忘/查询/序列化 + 会话状态持久化。

修复内容：
1. 添加会话状态持久化（原来只保存记忆，不保存会话）
2. 使用 logging 替换 print
3. 添加文件持久化（自动保存/加载）
4. 统一命名（去除中英文混用）
"""

import json
import logging
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from .logger import get_logger  # 使用 ai 模块的日志

logger = get_logger("memory")


class MemoryStore:
    """
    可学习的精确问答记忆库 + 会话状态管理。

    持久化格式：
    {
        "memories": {"问题": ["答案1", "答案2"]},
        "sessions": {"session_id": [["user", "msg"], ["ai", "reply"]]},
        "metadata": {"version": "1.0", "count": 42}
    }
    """

    VERSION = "1.0"

    def __init__(self, auto_save_path: Optional[str] = None):
        """
        Args:
            auto_save_path: 自动保存文件路径。设置后每次修改自动保存。
        """
        self._store: Dict[str, List[str]] = {}  # 问题 -> 答案列表
        self._sessions: Dict[str, List[Tuple[str, str]]] = {}  # session_id -> 对话历史
        self._auto_save_path = auto_save_path
        self._lock = threading.Lock()  # 线程安全

        # 启动时自动加载
        if self._auto_save_path and os.path.exists(self._auto_save_path):
            self._load_from_file(self._auto_save_path)

    # ============================================================
    # 学习 & 遗忘
    # ============================================================
    def learn(self, question: str, answer: str) -> bool:
        """教 AI 一个新的问答对。返回 True 表示学到了新东西。"""
        question = question.strip()
        if not question:
            logger.warning("尝试学习空问题，已忽略")
            return False

        with self._lock:
            if question not in self._store:
                self._store[question] = []
            if answer not in self._store[question]:
                self._store[question].append(answer)
                logger.debug("学习新知识：%s -> %s", question[:30], answer[:30])
                self._auto_save()
                return True
            return False

    def forget(self, question: str) -> bool:
        """忘记某个问题和它的所有答案。"""
        with self._lock:
            if question in self._store:
                del self._store[question]
                logger.info("忘记问题：%s", question[:30])
                self._auto_save()
                return True
            logger.warning("尝试忘记不存在的问题：%s", question[:30])
            return False

    def clear(self):
        """清空所有记忆和会话。"""
        with self._lock:
            count = len(self._store)
            self._store.clear()
            self._sessions.clear()
            logger.info("清空所有记忆（%d 条）和会话", count)
            self._auto_save()

    # ============================================================
    # 查询
    # ============================================================
    def get(self, question: str) -> Optional[str]:
        """精确匹配记忆中的问题，返回一个随机回复。"""
        import random
        q = question.strip()
        if q in self._store and self._store[q]:
            return random.choice(self._store[q])
        return None

    def fuzzy_search(self, text: str) -> Tuple[bool, Optional[str]]:
        """模糊搜索：检查 text 是否包含在记忆中的某个问题里或反之。"""
        for q in self._store.keys():
            if text in q or q in text:
                return True, q
        return False, None

    def search(self, keyword: str) -> List[str]:
        """按关键词搜索记忆中的问题（支持部分匹配）。"""
        results = [q for q in self._store.keys() if keyword in q]
        logger.debug("关键词搜索 '%s' 找到 %d 条结果", keyword, len(results))
        return results

    # ============================================================
    # 会话管理（新增：原来缺失的功能）
    # ============================================================
    def save_session(self, session_id: str, history: List[Tuple[str, str]]):
        """保存会话历史。"""
        with self._lock:
            self._sessions[session_id] = history.copy()
            logger.debug("保存会话 %s（%d 条记录）", session_id, len(history))
            self._auto_save()

    def load_session(self, session_id: str) -> List[Tuple[str, str]]:
        """加载会话历史。"""
        with self._lock:
            history = self._sessions.get(session_id, [])
            logger.debug("加载会话 %s（%d 条记录）", session_id, len(history))
            return history

    def delete_session(self, session_id: str) -> bool:
        """删除会话。"""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                logger.info("删除会话 %s", session_id)
                self._auto_save()
                return True
            return False

    def list_sessions(self) -> List[str]:
        """列出所有会话 ID。"""
        return list(self._sessions.keys())

    def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """获取会话摘要（用于 UI 展示）。"""
        history = self._sessions.get(session_id, [])
        return {
            "session_id": session_id,
            "message_count": len(history),
            "first_message": history[0][1] if history else "",
            "last_message": history[-1][1] if history else "",
        }

    # ============================================================
    # 序列化（增强：原来只保存记忆，现在保存完整状态）
    # ============================================================
    def to_dict(self) -> Dict[str, Any]:
        """导出完整状态（记忆 + 会话 + 元数据）。"""
        return {
            "version": self.VERSION,
            "memories": dict(self._store),
            "sessions": {k: v for k, v in self._sessions.items()},
            "metadata": {
                "memory_count": len(self._store),
                "session_count": len(self._sessions),
            },
        }

    def to_json(self, indent: int = 2) -> str:
        """导出为 JSON 字符串。"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def from_dict(self, data: Dict[str, Any]):
        """从字典恢复完整状态。"""
        with self._lock:
            version = data.get("version", "0.0")
            if version != self.VERSION:
                logger.warning("记忆文件版本不匹配：%s vs %s", version, self.VERSION)

            self._store = {k: v for k, v in data.get("memories", {}).items()}
            self._sessions = {k: v for k, v in data.get("sessions", {}).items()}
            logger.info(
                "从字典恢复状态：记忆 %d 条，会话 %d 个",
                len(self._store),
                len(self._sessions),
            )

    def from_json(self, json_str: str):
        """从 JSON 字符串恢复完整状态。"""
        try:
            data = json.loads(json_str)
            self.from_dict(data)
        except json.JSONDecodeError as e:
            logger.error("JSON 解析失败：%s", e)
            self._store = {}
            self._sessions = {}

    def save_to_file(self, filepath: str):
        """保存到文件（增强：保存完整状态）。"""
        try:
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(self.to_json())
            logger.info("状态已保存到 %s", filepath)
        except Exception as e:
            logger.error("保存失败 %s：%s", filepath, e)
            raise

    def load_from_file(self, filepath: str):
        """从文件恢复（增强：恢复完整状态）。"""
        if not os.path.exists(filepath):
            logger.warning("文件不存在：%s", filepath)
            return
        self._load_from_file(filepath)

    def _load_from_file(self, filepath: str):
        """内部加载方法。"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                self.from_json(f.read())
            logger.info("从文件恢复状态：%s", filepath)
        except Exception as e:
            logger.error("加载失败 %s：%s", filepath, e)
            raise

    def _auto_save(self):
        """自动保存（如果设置了 auto_save_path）。"""
        if self._auto_save_path:
            try:
                self.save_to_file(self._auto_save_path)
            except Exception as e:
                logger.error("自动保存失败：%s", e)

    # ============================================================
    # 统计
    # ============================================================
    def __len__(self) -> int:
        return len(self._store)

    @property
    def total_answers(self) -> int:
        return sum(len(v) for v in self._store.values())

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    def __repr__(self):
        return (
            f"<MemoryStore "
            f"memories={len(self)} "
            f"sessions={self.session_count} "
            f"answers={self.total_answers}>"
        )
