"""
专用响应器：处理特定类型的问题（时间、数学等）。

每个响应器实现 process(text) -> Optional[str] 接口。
参考 ChatterBot 的 TimeLogicAdapter / MathematicalEvaluation。
"""

from .time_responder import TimeResponder
from .math_responder import MathResponder
from .registry import RESPONDER_REGISTRY, register_responder, get_registered_responders

__all__ = ["TimeResponder", "MathResponder",
           "RESPONDER_REGISTRY", "register_responder", "get_registered_responders"]
