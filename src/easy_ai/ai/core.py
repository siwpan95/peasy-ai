"""
AICore: easy-ai 的主入口类 — 全面增强版。

零硬编码、配置驱动、可嵌入任意项目的通用 AI 对话核心。

增强特性：
- 置信度评分竞争模式（取代首命中返回）
- 专用响应器（时间/数学/自定义）
- 会话管理（多轮对话上下文 + 持久化）
- 意图识别（关键词提取 + 意图分类）
- 热重载配置（reload 不丢失记忆）
- 异步支持（真正的 async 接口）
- 日志系统（替换所有 print）
- 完整状态持久化（记忆 + 会话）

用法：
    from easy_ai.ai.core import AICore

    # 方式1：使用默认配置（零参数启动）
    ai = AICore()

    # 方式2：指定配置文件
    ai = AICore("config/default.json")

    # 方式3：从字典创建（无需文件）
    ai = AICore.from_dict({"rules": [...]})

    reply = ai.respond("你好")
"""

import json
import logging
import os
import asyncio
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Callable

from .config_loader import ConfigLoader
from .memory import MemoryStore
from .pipeline import ResponsePipeline, PipelineResult
from .session import SessionManager
from .intent import IntentClassifier
from .matchers.base import BaseMatcher, MatchResult
from .cache import ResponseCache, NoCache
from .logger import get_logger, ensure_logger  # 使用 ai 模块的日志

# 确保日志系统已初始化
ensure_logger()
logger = get_logger("core")


class AICore:
    """通用 AI 对话核心。

    不包含任何领域知识，所有行为通过配置文件定义。
    """

    VERSION = "1.0.0"

    def __init__(
        self,
        config_path: Optional[str] = None,
        *,
        memory_path: Optional[str] = None,
        log_level: int = logging.INFO,
        enable_session: bool = False,
        enable_intent: bool = False,
        cache: Optional[ResponseCache] = None,
        on_progress: Optional[Callable] = None,
    ):
        """
        Args:
            config_path: JSON 配置文件路径。为 None 时使用内置最小默认配置。
            memory_path: 记忆持久化文件路径。设置后自动保存/加载记忆和会话。
            log_level: 日志级别。
            enable_session: 是否启用会话管理（多轮对话上下文）。
            enable_intent: 是否启用意图识别（关键词提取 + 分类）。
            cache: 响应缓存策略。默认 NoCache()，可选 LRUCache(max_size=500)。
            on_progress: 进度回调 (stage: str, step: int, total: int) -> None。
        """
        self.config_path = config_path
        self.memory_path = memory_path

        # 初始化日志
        self.logger = logger

        # 加载配置
        try:
            self.config = ConfigLoader(config_path)
            self.logger.info("配置加载成功：%s", config_path or "内置默认配置")
        except Exception as e:
            self.logger.error("配置加载失败：%s", e)
            raise

        # 初始化记忆系统（支持持久化）
        self.memory = MemoryStore(auto_save_path=memory_path)
        if memory_path and os.path.exists(memory_path):
            self.logger.info("记忆已从文件恢复：%s", memory_path)

        # 初始化管道
        self.pipeline = ResponsePipeline(self.config, self.memory)

        # 可选模块
        self.session = SessionManager() if enable_session else None
        self.intent_clf = IntentClassifier() if enable_intent else None

        # 响应缓存
        self._cache = cache if cache is not None else NoCache()

        # 进度回调
        self.on_progress = on_progress

        self.logger.debug("AICore 初始化完成（版本=%s）", self.VERSION)

    # ============================================================
    # 主接口
    # ============================================================
    def respond(self, message: str, session_id: Optional[str] = None) -> str:
        """处理用户输入，返回回复。

        Args:
            message: 用户输入的文本。
            session_id: 可选的会话 ID，启用多轮上下文。

        Returns:
            AI 的回复文本。
        """
        if not message or not message.strip():
            self.logger.warning("收到空消息")
            return self.config.empty_input_response

        # 查缓存（无会话上下文时可用）
        if session_id is None:
            cached = self._cache.get(message.strip())
            if cached is not None:
                self.logger.debug("缓存命中：%s...", message[:30])
                return cached

        context = None
        if session_id and self.session:
            context = self.session.get_context(session_id)

        try:
            reply = self.pipeline.process(message, session_context=context,
                                          on_progress=self.on_progress)
        except Exception as e:
            self.logger.error("处理消息失败：%s", e, exc_info=True)
            reply = self.config.get("fallback_response", "抱歉，出了点问题。")

        # 写入缓存（无会话上下文时）
        if session_id is None:
            self._cache.put(message.strip(), reply)

        # 记录对话历史
        if session_id:
            if self.session:
                self.session.record(session_id, message, reply)
            # 持久化会话到记忆系统
            if self.memory_path:
                history = self.session.get_history(session_id) if self.session else []
                self.memory.save_session(session_id, history)

        return reply

    def respond_with_detail(
        self, message: str, session_id: Optional[str] = None
    ) -> PipelineResult:
        """处理输入并返回详细结果（含来源、置信度）。"""
        if not message or not message.strip():
            from .pipeline import PipelineResult
            return PipelineResult(
                reply=self.config.get("empty_input_response", "请说点什么吧。"),
                source="empty",
                confidence=0.0,
            )

        context = None
        if session_id and self.session:
            context = self.session.get_context(session_id)

        try:
            result = self.pipeline.process_with_detail(message, session_context=context)
        except Exception as e:
            self.logger.error("处理消息失败：%s", e, exc_info=True)
            from .pipeline import PipelineResult
            result = PipelineResult(
                reply=self.config.get("fallback_response", "抱歉，出了点问题。"),
                source="error",
                confidence=0.0,
            )

        if session_id and self.session:
            self.session.record(session_id, message, result.reply)

        return result

    async def respond_async(
        self, message: str, session_id: Optional[str] = None
    ) -> str:
        """异步版本：真正的非阻塞接口。

        使用 asyncio.to_thread 将同步代码放到线程池执行，
        避免阻塞事件循环（适用于 FastAPI / aiohttp 等异步框架）。
        """
        self.logger.debug("异步处理消息：%s...", message[:30])
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.respond, message, session_id
        )

    async def respond_with_detail_async(
        self, message: str, session_id: Optional[str] = None
    ) -> PipelineResult:
        """异步版本：返回详细结果。"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.respond_with_detail, message, session_id
        )

    # ============================================================
    # 会话式对话（一站式）
    # ============================================================
    def chat(self, session_id: str, message: str) -> str:
        """会话式聊天：自动启用 session 管理。

        Example:
            ai.enable_sessions()
            ai.chat("user_123", "你好")
            ai.chat("user_123", "我叫小明")
            ai.chat("user_123", "我叫什么")  # 有上下文了
        """
        if not self.session:
            self.enable_sessions()
        return self.respond(message, session_id=session_id)

    async def chat_async(self, session_id: str, message: str) -> str:
        """异步会话式聊天。"""
        if not self.session:
            self.enable_sessions()
        return await self.respond_async(message, session_id=session_id)

    # ============================================================
    # 学习 & 记忆
    # ============================================================
    def learn(self, question: str, answer: str) -> bool:
        """教 AI 一个新的问答对。"""
        result = self.memory.learn(question, answer)
        if result:
            self.logger.info("学会新知识：%s -> %s", question[:30], answer[:30])
        return result

    def forget(self, question: str) -> bool:
        """忘记某个问题和它的所有答案。"""
        return self.memory.forget(question)

    def clear_memory(self):
        """清空所有记忆。"""
        self.memory.clear()

    def search_memory(self, keyword: str) -> List[str]:
        """搜索记忆中的问题（新增：支持关键词搜索）。"""
        return self.memory.search(keyword)

    # ============================================================
    # 安全过滤
    # ============================================================
    def set_safety(self, keywords: List[str]):
        """设置安全过滤关键词。"""
        self.pipeline.set_safety_keywords(keywords)
        self.logger.info("安全过滤已启用，关键词数：%d", len(keywords))

    # ============================================================
    # 规则管理
    # ============================================================
    def add_rule(
        self,
        pattern: str,
        responses: List[str],
        confidence: float = None,
        source: str = "dynamic",
    ):
        """动态添加一条匹配规则。"""
        rule = {
            "pattern": pattern,
            "responses": responses,
            "source": source,  # 新增：记录规则来源
        }
        if confidence is not None:
            rule["confidence"] = confidence
        self.config.data.setdefault("rules", []).append(rule)
        self.logger.info("添加规则：%s", pattern[:30])

    def remove_rule(self, pattern: str) -> bool:
        """删除匹配规则（新增）。"""
        rules = self.config.data.get("rules", [])
        for i, rule in enumerate(rules):
            if rule.get("pattern") == pattern:
                rules.pop(i)
                self.logger.info("删除规则：%s", pattern[:30])
                return True
        return False

    # ============================================================
    # 匹配器管理
    # ============================================================
    def add_matcher(self, matcher: BaseMatcher):
        """添加自定义匹配器。"""
        self.pipeline.add_matcher(matcher)
        self.logger.debug("添加匹配器：%s", matcher.name)

    def get_matcher(self, name: str) -> Optional[BaseMatcher]:
        """获取匹配器。"""
        return self.pipeline.get_matcher(name)

    def remove_matcher(self, name: str) -> bool:
        """移除匹配器（新增）。"""
        return self.pipeline.remove_matcher(name)

    # ============================================================
    # 响应策略
    # ============================================================
    def set_selection_strategy(self, strategy: str):
        """设置响应选择策略: 'random', 'first', 'most_frequent'"""
        self.pipeline.set_selection_strategy(strategy)
        self.logger.debug("响应策略设置为：%s", strategy)

    # ============================================================
    # 会话管理
    # ============================================================
    def enable_sessions(self, max_history: int = 10, ttl_minutes: int = 30):
        """启用多轮对话会话管理。"""
        if not self.session:
            self.session = SessionManager(
                max_history=max_history, ttl_minutes=ttl_minutes
            )
            self.logger.info("会话管理已启用（max_history=%d, ttl=%dmin）", max_history, ttl_minutes)

    def get_session_context(self, session_id: str) -> Dict[str, Any]:
        """获取会话上下文。"""
        if not self.session:
            return {}
        return self.session.get_context(session_id)

    def get_chat_history(self, session_id: str, n: int = 5) -> List:
        """获取聊天历史。"""
        if not self.session:
            return []
        return self.session.get_history(session_id, n)

    def list_sessions(self) -> List[str]:
        """列出所有会话 ID（新增）。"""
        if not self.session:
            return []
        return self.session.list_sessions()

    def delete_session(self, session_id: str) -> bool:
        """删除会话（新增）。"""
        if not self.session:
            return False
        result = self.session.delete_session(session_id)
        if result and self.memory_path:
            self.memory.delete_session(session_id)
        return result

    # ============================================================
    # 意图识别
    # ============================================================
    def enable_intent(self):
        """启用意图识别。"""
        if not self.intent_clf:
            self.intent_clf = IntentClassifier()
            self.logger.info("意图识别已启用")

    def classify_intent(self, text: str) -> Tuple[str, float]:
        """分类意图。返回 (意图标签, 置信度)。"""
        if not self.intent_clf:
            self.enable_intent()
        return self.intent_clf.classify(text)

    def extract_keywords(self, text: str, top_n: int = 5) -> List[Tuple[str, float]]:
        """从输入中提取关键词。"""
        if not self.intent_clf:
            self.enable_intent()
        return self.intent_clf.extract_keywords(text, top_n)

    # ============================================================
    # 热重载
    # ============================================================
    def reload(self, config_path: Optional[str] = None):
        """热重载配置（不丢失记忆和会话）。

        Args:
            config_path: 新的配置文件路径。为 None 时重新加载原路径。
        """
        path = config_path or self.config_path
        try:
            self.config = ConfigLoader(path)
            self.pipeline = ResponsePipeline(self.config, self.memory)
            self.config_path = path
            self.logger.info("配置已热重载：%s", path)
        except Exception as e:
            self.logger.error("热重载失败：%s", e)
            raise

    # ============================================================
    # 存档 & 读档（增强：保存完整状态）
    # ============================================================
    def save(self, filepath: Optional[str] = None):
        """保存完整状态（记忆 + 会话）。

        Args:
            filepath: 保存路径。为 None 时使用 memory_path。
        """
        path = filepath or self.memory_path
        if not path:
            self.logger.warning("未指定保存路径，使用默认路径：memory.json")
            path = "memory.json"
        self.memory.save_to_file(path)
        self.logger.info("状态已保存：%s", path)

    def load(self, filepath: Optional[str] = None):
        """加载完整状态（记忆 + 会话）。

        Args:
            filepath: 加载路径。为 None 时使用 memory_path。
        """
        path = filepath or self.memory_path
        if not path:
            self.logger.error("未指定加载路径")
            return
        self.memory.load_from_file(path)
        self.logger.info("状态已加载：%s", path)

    def export_state(self) -> str:
        """导出完整状态为 JSON 字符串。"""
        return self.memory.to_json()

    def import_state(self, json_str: str):
        """从 JSON 字符串导入完整状态。"""
        try:
            self.memory.from_json(json_str)
            self.logger.info("状态已导入")
        except Exception as e:
            self.logger.error("状态导入失败：%s", e)
            raise

    # ============================================================
    # 管道控制
    # ============================================================
    def enable_stage(self, name: str):
        """启用管道阶段。"""
        self.pipeline.enable_stage(name)
        self.logger.debug("管道阶段已启用：%s", name)

    def disable_stage(self, name: str):
        """禁用管道阶段。"""
        self.pipeline.disable_stage(name)
        self.logger.debug("管道阶段已禁用：%s", name)

    def get_pipeline_info(self) -> Dict[str, Any]:
        """获取管道信息（新增）。"""
        return self.pipeline.get_info()

    # ============================================================
    # 向后兼容（旧 API）
    # ============================================================
    def export_memory(self) -> str:
        """导出记忆（向后兼容）。"""
        return self.memory.to_json()

    def import_memory(self, json_str: str):
        """导入记忆（向后兼容）。"""
        self.memory.from_json(json_str)

    def fuzzy_match(self, text: str, threshold: float = 0.6):
        """模糊匹配（向后兼容）。"""
        return self.memory.fuzzy_search(text)

    # ============================================================
    # 缓存管理
    # ============================================================
    def clear_cache(self):
        """清空响应缓存。"""
        self._cache.clear()
        self.logger.debug("响应缓存已清空")

    @property
    def cache_size(self) -> int:
        return self._cache.size()

    # ============================================================
    # 信息
    # ============================================================
    @property
    def name(self) -> str:
        return self.config.name

    @property
    def memory_count(self) -> int:
        return len(self.memory)

    @property
    def session_count(self) -> int:
        return self.memory.session_count if self.memory else 0

    @property
    def matchers_info(self) -> List[Dict]:
        return [{"name": m.name, "priority": m.priority} for m in self.pipeline.matchers]

    @property
    def version(self) -> str:
        return self.VERSION

    def get_info(self) -> Dict[str, Any]:
        """获取 AICore 完整信息（新增）。"""
        return {
            "version": self.VERSION,
            "name": self.name,
            "memory_count": self.memory_count,
            "session_count": self.session_count,
            "matchers": self.matchers_info,
            "config_path": self.config_path,
            "memory_path": self.memory_path,
        }

    def __repr__(self):
        extras = []
        if self.session:
            extras.append(f"sessions={self.session_count}")
        if self.intent_clf:
            extras.append("intent")
        info = " ".join(extras)
        return (
            f"<AICore name='{self.name}' "
            f"memory={self.memory_count} "
            f"version={self.VERSION} "
            f"{info}>".strip()
        )


# ============================================================
# 便捷函数
# ============================================================
def create(config_path: Optional[str] = None, **kwargs) -> AICore:
    """快捷创建 AICore 实例。"""
    return AICore(config_path, **kwargs)


def from_dict(config_dict: Dict[str, Any], **kwargs) -> AICore:
    """从字典创建 AICore（跳过文件读取）。"""
    import tempfile
    tmpfile = Path(tempfile.gettempdir()) / "_easy_ai_temp_config.json"
    with open(tmpfile, "w", encoding="utf-8") as f:
        json.dump(config_dict, f, ensure_ascii=False, indent=2)
    ai = AICore(str(tmpfile), **kwargs)
    try:
        tmpfile.unlink()
    except OSError:
        pass
    return ai


def from_config(config_path: Optional[str] = None, **kwargs) -> AICore:
    """别名：create 的别名，更符合语义。"""
    return create(config_path, **kwargs)
