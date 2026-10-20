"""
匹配器抽象基类 — 置信度评分体系。

每个匹配器的 match() 返回 MatchResult，包含回复文本和置信度 (0~1)。
管道收集所有结果，选置信度最高者返回。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional


@dataclass
class MatchResult:
    """匹配结果：包含回复文本和置信度。

    confidence: 0.0 = 完全不匹配, 1.0 = 确定匹配
    """
    reply: str
    confidence: float = 1.0
    source: str = ""  # 匹配器名称，方便调试
    metadata: Dict[str, Any] = field(default_factory=dict)  # 附加调试信息

    def __bool__(self):
        return self.reply is not None and self.confidence > 0


class BaseMatcher(ABC):
    """所有匹配器的基类。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.name = self.config.get("name", self.__class__.__name__)
        self.priority = self.config.get("priority", 50)
        self.min_confidence = self.config.get("min_confidence", 0.0)

    @abstractmethod
    def match(self, text: str, rules: List[Dict[str, Any]]) -> Optional[MatchResult]:
        """尝试匹配输入文本。

        Args:
            text: 用户输入
            rules: 规则列表

        Returns:
            MatchResult 或 None（无法匹配）。
        """
        ...

    # 向后兼容：返回纯文本的 match_text
    def match_text(self, text: str, rules: List[Dict[str, Any]]) -> Optional[str]:
        result = self.match(text, rules)
        return result.reply if result else None

    def can_process(self, text: str) -> bool:
        """快速判断能否处理（子类可覆盖以提升性能）。"""
        return True

    def __repr__(self):
        return f"<{self.name} priority={self.priority} min_conf={self.min_confidence}>"
