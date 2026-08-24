"""
UI 层：界面渲染，纯表现，不含业务逻辑。

模式：
- Chat UI：类微信聊天界面（气泡 + 选项按钮）
- RPG UI：类 RPG 对话框（属性条 + 立绘 + 选项，预留）
"""

from .interface import UIInterface
from .chat_ui import ChatUI

__all__ = ["UIInterface", "ChatUI"]
