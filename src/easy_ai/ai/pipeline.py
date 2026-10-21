"""
响应管道：中间件链 + 置信度评分竞争模式。

管道阶段：
1. 空输入检查
2. 安全过滤
3. 专用响应器（时间/数学/...）
4. 精确记忆匹配（confidence = 1.0）
5. 规则匹配器链（收集所有 MatchResult，按置信度排序）
6. 最终兜底

每个阶段可独立启用/禁用。匹配器按优先级 + 置信度竞争选择最优回复。
"""

import random
from typing import Dict, List, Any, Optional, Tuple, Callable
from dataclasses import dataclass

from .config_loader import ConfigLoader
from .logger import get_logger
from .memory import MemoryStore
from .matchers import BaseMatcher, MatchResult, MATCHER_REGISTRY
from .responders.registry import RESPONDER_REGISTRY

logger = get_logger("ai.pipeline")  # 与 core.py 一致：传短名，get_logger 自行加 easy_ai. 前缀


@dataclass
class PipelineResult:
    """管道处理结果（含调试信息）。"""
    reply: str
    source: str = ""
    confidence: float = 0.0
    details: Dict[str, Any] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


class ResponsePipeline:
    """可配置的响应生成管道。"""

    # 响应选择策略
    SELECTION_STRATEGIES = ("random", "first", "most_frequent")

    def __init__(self, config: ConfigLoader, memory: MemoryStore):
        self.config = config
        self.memory = memory

        # 匹配器
        self.matchers: List[BaseMatcher] = self._init_matchers()

        # 专用响应器
        self.responders: List[Callable] = self._init_responders()

        # 安全配置
        safety = config.get_safety()
        self.safety_enabled = safety.get("enabled", False)
        self.safety_keywords = safety.get("keywords", [])
        self.safety_responses = safety.get("response", ["抱歉，无法回答。"])

        # 管道阶段开关
        self.stages: Dict[str, bool] = {
            "safety": self.safety_enabled and bool(self.safety_keywords),
            "responders": True,
            "memory": True,
            "matchers": len(self.matchers) > 0,
            "fallback": True,
        }

        # 响应选择策略
        pipeline_config = config.data.get("pipeline", {})
        self.selection_strategy = pipeline_config.get("response_selection", "random")
        if self.selection_strategy not in self.SELECTION_STRATEGIES:
            self.selection_strategy = "random"

        # 专用响应器配置
        responder_config = config.data.get("responders", {})
        self.responder_enabled = responder_config

    # ============================================================
    # 初始化
    # ============================================================
    def _init_matchers(self) -> List[BaseMatcher]:
        """从注册表实例化匹配器（对标 ComfyUI NODE_CLASS_MAPPINGS）。

        通过 MATCHER_REGISTRY 自动发现所有已注册的匹配器，
        根据配置决定是否启用。第三方匹配器在 import 时自动注册。
        """
        matcher_config = self.config.get_matchers()
        instances: List[BaseMatcher] = []

        for name, matcher_cls in MATCHER_REGISTRY.items():
            cfg = matcher_config.get(name, {})
            if not cfg.get("enabled", True):
                continue
            try:
                instances.append(matcher_cls(cfg))
            except ImportError as e:
                # 可选依赖缺失（如 neural 需要 numpy）时优雅降级：跳过该匹配器，
                # 而不是让整个 AICore 起不来。核心能力为零依赖，装齐依赖即自动恢复。
                logger.warning("匹配器 %s 因缺少可选依赖被跳过：%s", name, e)

        instances.sort(key=lambda m: m.priority)
        return instances

    def _init_responders(self) -> List[Callable]:
        """从注册表实例化响应器（对标 ComfyUI 节点注册）。

        通过 RESPONDER_REGISTRY 自动发现所有已注册的响应器，
        根据配置决定是否启用。第三方响应器在 import 时自动注册。
        """
        responders = []
        rconfig = self.config.data.get("responders", {})

        for name, responder_cls in RESPONDER_REGISTRY.items():
            cfg = rconfig.get(name, {})
            if cfg.get("enabled", False):
                responders.append(responder_cls(cfg))

        return responders

    def add_matcher(self, matcher: BaseMatcher):
        self.matchers.append(matcher)
        self.matchers.sort(key=lambda m: getattr(m, "priority", 50))
        self.stages["matchers"] = True

    def add_responder(self, responder: Callable):
        self.responders.append(responder)

    # ============================================================
    # 主处理入口
    # ============================================================
    def process(self, text: str, rules: Optional[List[Dict[str, Any]]] = None,
                session_context: Optional[Dict[str, Any]] = None,
                on_progress: Optional[Callable] = None) -> str:
        """按管道顺序处理输入，返回回复。

        Args:
            text: 用户输入。
            rules: 规则列表（可选，默认从配置加载）。
            session_context: 会话上下文。
            on_progress: 进度回调 (stage: str, step: int, total: int) -> None。
        """
        if rules is None:
            rules = self.config.get_rules()

        text = text.strip()
        total_stages = 6

        # 阶段 1: 空输入
        if not text:
            self._emit_progress(on_progress, "空输入检查", 1, total_stages)
            return self.config.empty_input_response

        # 阶段 2: 安全过滤
        self._emit_progress(on_progress, "安全过滤", 2, total_stages)
        if self.stages.get("safety") and self._check_safety(text):
            return random.choice(self.safety_responses)

        # 阶段 3: 专用响应器（时间/数学等）
        self._emit_progress(on_progress, "专用响应器", 3, total_stages)
        if self.stages.get("responders"):
            for responder in self.responders:
                result = responder.process(text) if hasattr(responder, 'process') else responder(text)
                if result:
                    return result

        # 阶段 4: 精确记忆匹配
        self._emit_progress(on_progress, "记忆匹配", 4, total_stages)
        if self.stages.get("memory"):
            memory_reply = self.memory.get(text)
            if memory_reply is not None:
                return memory_reply

        # 阶段 5: 规则匹配器链（置信度竞争模式）
        self._emit_progress(on_progress, "匹配器竞争", 5, total_stages)
        if self.stages.get("matchers"):
            best = self._competitive_match(text, rules, session_context)
            if best:
                return best.reply

        # 阶段 6: 最终兜底
        self._emit_progress(on_progress, "兜底回复", 6, total_stages)
        if self.stages.get("fallback"):
            return self.config.fallback_response

        return "..."

    @staticmethod
    def _emit_progress(on_progress: Optional[Callable], stage: str, step: int, total: int):
        """发出进度事件。"""
        if on_progress:
            on_progress(stage, step, total)

    def process_with_detail(self, text: str, rules: Optional[List[Dict[str, Any]]] = None,
                            session_context: Optional[Dict[str, Any]] = None) -> PipelineResult:
        """处理输入并返回详细信息（用于调试）。"""
        reply = self.process(text, rules, session_context)
        # 推断来源
        source = "unknown"
        if reply == self.config.empty_input_response:
            source = "empty_input"
        elif reply in self.safety_responses:
            source = "safety"
        elif self.memory.get(text.strip()) == reply:
            source = "memory"
        elif reply == self.config.fallback_response:
            source = "fallback"
        else:
            # 检查是否是匹配器输出
            for m in self.matchers:
                if hasattr(m, 'last_confidence'):
                    source = m.name
                    break
        return PipelineResult(reply=reply, source=source)

    # ============================================================
    # 置信度竞争匹配
    # ============================================================
    def _competitive_match(self, text: str, rules: List[Dict[str, Any]],
                           session_context: Optional[Dict[str, Any]] = None) -> Optional[MatchResult]:
        """收集所有匹配器的结果，选置信度最高的。"""
        all_results: List[MatchResult] = []

        for matcher in self.matchers:
            if not matcher.can_process(text):
                continue
            result = matcher.match(text, rules)
            if result and result.confidence >= (matcher.min_confidence or 0.0):
                all_results.append(result)

        if not all_results:
            return None

        # 按置信度降序排列
        all_results.sort(key=lambda r: r.confidence, reverse=True)

        # 响应选择策略
        best = all_results[0]
        if self.selection_strategy == "most_frequent" and len(all_results) > 1:
            # 从同置信度的结果中选出现最多的
            top_conf = best.confidence
            top_group = [r for r in all_results if abs(r.confidence - top_conf) < 0.001]
            freq = {}
            for r in top_group:
                freq[r.reply] = freq.get(r.reply, 0) + 1
            best_reply = max(freq, key=lambda k: freq[k])
            for r in top_group:
                if r.reply == best_reply:
                    best = r
                    break
        elif self.selection_strategy == "first":
            best = all_results[0]

        # 存储最后置信度，方便调试
        for m in self.matchers:
            if m.name == best.source:
                m.last_confidence = best.confidence

        return best

    # ============================================================
    # 安全过滤
    # ============================================================
    def _check_safety(self, text: str) -> bool:
        for kw in self.safety_keywords:
            if kw in text:
                return True
        return False

    # ============================================================
    # 辅助方法
    # ============================================================
    def enable_stage(self, name: str):
        self.stages[name] = True

    def disable_stage(self, name: str):
        self.stages[name] = False

    def set_safety_keywords(self, keywords: List[str]):
        self.safety_keywords = list(keywords)
        self.stages["safety"] = bool(keywords)

    def set_safety_enabled(self, enabled: bool):
        """快捷开/关安全过滤（不改变关键词列表）。"""
        self.safety_enabled = enabled
        self.stages["safety"] = enabled and bool(self.safety_keywords)

    def set_selection_strategy(self, strategy: str):
        if strategy in self.SELECTION_STRATEGIES:
            self.selection_strategy = strategy

    def get_matcher(self, name: str) -> Optional[BaseMatcher]:
        for m in self.matchers:
            if m.name == name:
                return m
        return None

    def remove_matcher(self, name: str) -> bool:
        """按名称移除匹配器，返回是否移除成功。"""
        for i, m in enumerate(self.matchers):
            if m.name == name:
                self.matchers.pop(i)
                return True
        return False

    def get_info(self) -> Dict[str, Any]:
        """管道状态快照：阶段开关 / 匹配器清单 / 选择策略 / 安全配置。"""
        return {
            "stages": dict(self.stages),
            "matchers": [repr(m) for m in self.matchers],
            "selection_strategy": self.selection_strategy,
            "safety_enabled": self.safety_enabled,
            "safety_keywords": list(self.safety_keywords),
            "responders": len(self.responders),
        }

    def __repr__(self):
        return (f"<ResponsePipeline stages={self.stages} "
                f"matchers={len(self.matchers)} strategy={self.selection_strategy}>")
