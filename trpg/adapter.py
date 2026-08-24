"""
适配器：连接叙事引擎和 AI Core 的桥梁。

职责：
1. 用户输入 → 判断是游戏指令还是闲聊
2. 游戏指令 → 交给引擎处理
3. 闲聊 → 交给 AI Core 处理
4. 维护引擎 ↔ UI 的双向通信

零硬编码：所有判断阈值、指令前缀可在配置中定义。
"""

import os
import sys
from typing import Optional, Dict, Any

_EASYAI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _EASYAI_DIR)

from ai.core import AICore
from engine.core import NarrativeEngine


class GameAdapter:
    """引擎 + AI Core 的整合适配器。

    使用方式：
        engine = NarrativeEngine("data")
        ai = AICore("config.json")
        adapter = GameAdapter(engine, ai)

        # 处理用户输入
        result = adapter.process("你好")       # → AI 闲聊
        result = adapter.process("1")          # → 引擎选项
        result = adapter.process("派兵")        # → 引擎选项（关键词匹配）
    """

    def __init__(self, engine: NarrativeEngine, ai: AICore):
        self.engine = engine
        self.ai = ai

        # 可配置：指令前缀
        self.command_prefixes = ["查看", "选择"]

    # ============================================================
    # 主处理入口
    # ============================================================
    def process(self, user_input: str) -> Dict[str, Any]:
        """处理用户输入，返回统一结果字典。

        Returns:
            {
                "type": "scene" | "ending" | "ai_chat" | "ai_learn",
                "speaker": "角色名" (仅 scene),
                "text": "显示文本",
                "options": [...] (仅 scene),
                "attributes": {...} (当前属性),
                "is_ended": bool,
            }
        """
        text = user_input.strip()

        # ---- 教学指令 ----
        if self._is_teach_command(text):
            q, a = self._parse_teach(text)
            self.ai.learn(q, a)
            return {
                "type": "ai_learn",
                "text": f"好的，我记住了。「{q}」→「{a}」",
                "attributes": self.engine.attributes,
                "is_ended": self.engine.is_ended,
            }

        # ---- 数字选项 ----
        if text.isdigit():
            index = int(text) - 1
            return self._handle_option(index)

        # ---- 关键词匹配选项 ----
        available = self.engine.get_available_options()
        for i, opt in enumerate(available):
            if self._text_matches(opt.text, text):
                return self._handle_option(i)

        # ---- 命令 ----
        if self._is_command(text):
            return self._handle_command(text)

        # ---- 兜底：AI 闲聊 ----
        response = self.ai.respond(text)
        return {
            "type": "ai_chat",
            "text": response,
            "attributes": self.engine.attributes,
            "is_ended": self.engine.is_ended,
        }

    # ============================================================
    # 内部逻辑
    # ============================================================
    def _handle_option(self, index: int) -> Dict[str, Any]:
        """执行引擎选项。"""
        success = self.engine.choose_option(index)

        if not success:
            return {
                "type": "ai_chat",
                "text": "无效的选项。",
                "attributes": self.engine.attributes,
                "is_ended": self.engine.is_ended,
            }

        # 检查结局
        if self.engine.is_ended:
            return {
                "type": "ending",
                "text": self.engine.get_ending_text(),
                "attributes": self.engine.attributes,
                "is_ended": True,
            }

        # 渲染下一场景
        return self._render_current_scene()

    def _render_current_scene(self) -> Dict[str, Any]:
        """将当前场景包装为结果字典。"""
        scene = self.engine.get_current_scene()
        if not scene:
            return {
                "type": "ending",
                "text": "故事在此结束。",
                "attributes": self.engine.attributes,
                "is_ended": True,
            }

        # 获取角色名称
        char_info = self.engine.data.get_character(scene.speaker)
        speaker_name = char_info.get("name", scene.speaker)

        # 可用选项
        available = self.engine.get_available_options()
        options = [{"text": o.text, "index": i, "enabled": True}
                   for i, o in enumerate(available)]

        return {
            "type": "scene",
            "speaker": speaker_name,
            "speaker_id": scene.speaker,
            "avatar": char_info.get("avatar"),
            "text": scene.text,
            "options": options,
            "attributes": self.engine.attributes,
            "is_ended": False,
        }

    def _handle_command(self, text: str) -> Dict[str, Any]:
        """处理游戏内命令。"""
        if text.startswith("查看"):
            attr = text[2:].strip()
            if attr in self.engine.state.attributes:
                val = self.engine.state.attributes[attr]
                return {
                    "type": "ai_chat",
                    "text": f"{attr}：{val}",
                    "attributes": self.engine.attributes,
                    "is_ended": self.engine.is_ended,
                }
        return {
            "type": "ai_chat",
            "text": "未知命令。你可以直接输入数字选择选项，或输入关键词。",
            "attributes": self.engine.attributes,
            "is_ended": self.engine.is_ended,
        }

    # ============================================================
    # 工具方法
    # ============================================================
    def _is_teach_command(self, text: str) -> bool:
        return text.startswith("问：") or text.startswith("问:")

    def _parse_teach(self, text: str) -> tuple:
        import re
        m = re.match(r'问[：:]\s*(.+?)\s*答[：:]\s*(.+)', text)
        if m:
            return m.group(1), m.group(2)
        return text, "已记录"

    def _is_command(self, text: str) -> bool:
        return any(text.startswith(p) for p in self.command_prefixes)

    def _text_matches(self, option_text: str, user_input: str) -> bool:
        """简单关键词匹配。"""
        # 双向包含
        if option_text in user_input or user_input in option_text:
            return True
        # 提取选项关键词
        keywords = option_text.split()
        match_count = sum(1 for kw in keywords if kw in user_input)
        return match_count >= len(keywords) * 0.5

    # ============================================================
    # 状态查询
    # ============================================================
    def get_scene_info(self) -> Dict[str, Any]:
        """获取当前场景信息（给 UI 初始化用）。"""
        return self._render_current_scene()

    @property
    def is_ended(self) -> bool:
        return self.engine.is_ended
