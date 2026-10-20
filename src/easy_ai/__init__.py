"""
easy-ai: 通用 AI 对话框架
===========================

零硬编码、配置驱动、可嵌入任意项目的轻量 AI 核心。

发行名 easya1（`pip install easya1`）；导入名 easy_ai（`import easy_ai`）。
自 1.0.0 起为命名空间包，不再需要把仓库根目录塞进 sys.path。

目录结构：
    ai/     — AI 大脑（AICore、匹配器、记忆、意图识别）
    engine/ — 叙事引擎（分支剧情、条件求值）
    trpg/   — TRPG 训练工具（随机表、骰子、AI 训练器、paotuan 集成）
    ui/     — 图形界面（tkinter 聊天窗口）
    data/   — 示例数据
    paotuan/— 内置「迷失之镜」TRPG 子应用（独立自举，非库代码）
    config/ — 配置文件

用法：
    from easy_ai import AICore, create

    ai = create()                    # 零参数，内置默认配置
    ai = AICore("config/default.json")
"""

from easy_ai.ai.core import AICore, create, from_dict
from easy_ai.ai.config_loader import ConfigLoader
from easy_ai.ai.memory import MemoryStore
from easy_ai.ai.pipeline import ResponsePipeline, PipelineResult
from easy_ai.ai.session import SessionManager
from easy_ai.ai.intent import IntentClassifier

__version__ = "1.0.0"
__all__ = [
    "AICore", "ConfigLoader", "MemoryStore", "ResponsePipeline",
    "PipelineResult", "SessionManager", "IntentClassifier",
    "create", "from_dict",
]
