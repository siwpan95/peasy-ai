"""
easy-ai: 通用 AI 对话框架
===========================

零硬编码、配置驱动、可嵌入任意项目的轻量 AI 核心。

目录结构：
    ai/     — AI 大脑（AICore、匹配器、记忆、意图识别）
    engine/ — 叙事引擎（分支剧情、条件求值）
    trpg/   — TRPG 训练工具（随机表、骰子、AI 训练器、paotuan 集成）
    ui/     — 图形界面（tkinter 聊天窗口）
    data/   — 示例数据
    paotuan/— 内置 paotuan TRPG 引擎
    config/ — 配置文件

用法：
    import sys; sys.path.insert(0, 'D:/allin/tools/easy-ai')
    from ai.core import AICore
    ai = AICore("config/default.json")
"""

from ai.core import AICore, create, from_dict
from ai.config_loader import ConfigLoader
from ai.memory import MemoryStore
from ai.pipeline import ResponsePipeline, PipelineResult
from ai.session import SessionManager
from ai.intent import IntentClassifier

__version__ = "3.2.0"
__all__ = [
    "AICore", "ConfigLoader", "MemoryStore", "ResponsePipeline",
    "PipelineResult", "SessionManager", "IntentClassifier",
    "create", "from_dict",
]
