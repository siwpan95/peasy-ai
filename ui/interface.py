"""
UI 抽象接口：定义所有界面类型的统一方法。

引擎通过此接口驱动界面，不关心具体渲染方式。
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class UIInterface(ABC):
    """所有 UI 实现的抽象基类。"""

    @abstractmethod
    def run(self):
        """启动主循环。"""
        ...

    @abstractmethod
    def show_scene(self, speaker_name: str, speaker_avatar: Optional[str],
                   text: str, options: List[Dict[str, Any]]):
        """
        渲染当前场景。

        Args:
            speaker_name: 说话人名称
            speaker_avatar: 说话人头像路径（None 表示无）
            text: 对话文本
            options: 选项列表 [{"text": "选项名", "index": 0}, ...]
        """
        ...

    @abstractmethod
    def show_attributes(self, attributes: Dict[str, int],
                        max_values: Optional[Dict[str, int]] = None):
        """渲染属性条。"""
        ...

    @abstractmethod
    def show_ending(self, text: str):
        """显示结局。"""
        ...

    @abstractmethod
    def add_ai_message(self, text: str):
        """显示 AI 闲聊消息。"""
        ...

    def on_option_chosen(self, index: int):
        """选项被点击时由子类调用，触发引擎处理。"""
        # 子类覆盖此方法连接引擎
        pass

    def on_free_text(self, text: str):
        """自由文本输入时由子类调用，触发 AI 处理。"""
        pass
