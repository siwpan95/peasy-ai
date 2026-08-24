"""
正则表达式匹配器：按规则库顺序匹配，返回置信度评分。

完全匹配 → confidence = 1.0
捕获组匹配 → confidence = 0.95
兜底 .* 匹配 → confidence = 0.01
"""

import re
import random
from typing import Dict, List, Any, Optional

from .base import BaseMatcher, MatchResult
from .registry import register_matcher


@register_matcher("regex")
class RegexMatcher(BaseMatcher):
    """基于正则表达式的模式匹配器。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "RegexMatcher"
        cfg = config or {}
        self.priority = cfg.get("priority", 10)

        default_reflections = {
            "我": "你", "你": "我",
            "我的": "你的", "你的": "我的",
            "我是": "你是", "你是": "我是"
        }
        self.reflections = cfg.get("reflections", default_reflections)

    def set_reflections(self, reflections: Dict[str, str]):
        self.reflections = dict(reflections)

    # ============================================================
    # 核心匹配（返回 MatchResult）
    # ============================================================
    def match(self, text: str, rules: List[Dict[str, Any]]) -> Optional[MatchResult]:
        """按顺序尝试每条规则，返回第一个命中的 MatchResult。

        每条规则可自定义 confidence 字段覆盖默认评分逻辑。
        """
        for rule in rules:
            pattern = rule.get("pattern", "")
            responses = rule.get("responses", [])
            if not responses:
                continue

            m = re.match(pattern, text, re.IGNORECASE)
            if m:
                reply = random.choice(responses)
                if m.groups():
                    reply = self._apply_capture_groups(reply, m)

                # 置信度计算
                confidence = self._compute_confidence(rule, pattern, m)
                return MatchResult(reply=reply, confidence=confidence, source=self.name)

        return None

    def _compute_confidence(self, rule: Dict, pattern: str, match: re.Match) -> float:
        """根据匹配质量计算置信度。"""
        # 规则显式指定
        if "confidence" in rule:
            return float(rule["confidence"])

        # 兜底规则 .* → 极低置信度
        if pattern == ".*":
            return 0.01

        # 完整句子匹配 → 高置信度
        groups = match.groups()
        if groups:
            return 0.95
        return 1.0

    # ============================================================
    # 文本反射
    # ============================================================
    def _reflect(self, text: str) -> str:
        sorted_pairs = sorted(self.reflections.items(), key=lambda x: -len(x[0]))
        result = text
        placeholders = {}
        for i, (old, new) in enumerate(sorted_pairs):
            ph = f"__REF{i}__"
            placeholders[ph] = new
            result = result.replace(old, ph)
        for ph, replacement in placeholders.items():
            result = result.replace(ph, replacement)
        return result

    def _apply_capture_groups(self, reply: str, match: re.Match) -> str:
        groups = match.groups()
        try:
            reflected = [self._reflect(g) for g in groups]
            return reply.format(*reflected)
        except (IndexError, KeyError):
            pass
        if groups:
            return reply.replace("{0}", self._reflect(groups[0]))
        return reply
