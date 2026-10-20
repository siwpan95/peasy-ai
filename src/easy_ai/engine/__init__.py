"""
叙事引擎：事件调度、条件求值、属性管理、数据加载。

所有名称（属性名、角色名、场景ID）来自 JSON 配置，代码零硬编码。
"""

from .models import Scene, Option, GameState
from .conditions import ConditionEvaluator
from .core import NarrativeEngine
from .data_loader import DataLoader

__all__ = [
    "Scene", "Option", "GameState",
    "ConditionEvaluator", "NarrativeEngine", "DataLoader",
]
