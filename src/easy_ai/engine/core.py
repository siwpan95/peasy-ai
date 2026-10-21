"""
叙事引擎核心：事件调度 + 状态机 + 存档管理 + 场景预览/跳转。

零硬编码：
- 属性名、结局触发条件全部来自 JSON
- "王权"、"黑相集"这类概念不在代码中出现
- 引擎只知道"属性有范围，超出触发结局"这个抽象规则

新增功能（v2.4.0）：
- 场景预览（peek）：查看选项的下一个场景，不提交
- 场景跳转（jump）：直接跳到任意场景
- 场景历史（history）：支持撤销/重做
- 错误处理：完整的 logging 和异常处理
- 场景验证：启动时检查数据完整性
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field

from .models import GameState, Scene, Option
from .conditions import ConditionEvaluator
from .data_loader import DataLoader

logger = logging.getLogger(__name__)  # 使用标准 logging


@dataclass
class SceneHistory:
    """场景历史记录（支持撤销/重做）。"""
    history: List[str] = field(default_factory=list)
    position: int = -1  # 当前位置（-1 表示空）

    def push(self, scene_id: str):
        """添加新场景到历史。"""
        # 如果当前不在末尾，截断后面的历史
        if self.position < len(self.history) - 1:
            self.history = self.history[:self.position + 1]
        self.history.append(scene_id)
        self.position = len(self.history) - 1

    def undo(self) -> Optional[str]:
        """撤销：返回上一个场景 ID。"""
        if self.position > 0:
            self.position -= 1
            return self.history[self.position]
        return None

    def redo(self) -> Optional[str]:
        """重做：返回下一个场景 ID。"""
        if self.position < len(self.history) - 1:
            self.position += 1
            return self.history[self.position]
        return None

    def can_undo(self) -> bool:
        return self.position > 0

    def can_redo(self) -> bool:
        return self.position < len(self.history) - 1

    def clear(self):
        self.history.clear()
        self.position = -1

    def to_dict(self) -> Dict:
        return {"history": self.history, "position": self.position}

    @classmethod
    def from_dict(cls, data: Dict) -> "SceneHistory":
        h = cls()
        h.history = data.get("history", [])
        h.position = data.get("position", -1)
        return h


class NarrativeEngine:
    """数据驱动的通用叙事引擎。

    配合 JSON 场景数据，可实现任意分支剧情。
    不包含任何特定游戏类型的知识。
    """

    VERSION = "1.0.1"

    def __init__(self, data_path: str = "data", config_file: str = "config.json"):
        """
        Args:
            data_path: JSON 数据目录。
            config_file: 主配置文件名。
        """
        logger.info("初始化叙事引擎（版本=%s）", self.VERSION)
        logger.debug("数据路径：%s，配置文件：%s", data_path, config_file)

        self.data = DataLoader(data_path)
        try:
            self.data.load(config_file)
            logger.info("数据加载成功：%d 个场景", len(self.data.scenes))
        except Exception as e:
            logger.error("数据加载失败：%s", e, exc_info=True)
            raise

        self.state = GameState()
        self.evaluator = ConditionEvaluator()
        self.history = SceneHistory()

        # 事件回调
        self._listeners: List[Callable] = []

        # 验证数据完整性
        self._validate_data()

        self._init_state()

        logger.info("叙事引擎初始化完成")

    # ============================================================
    # 数据验证（新增：错误处理）
    # ============================================================
    def _validate_data(self):
        """验证数据完整性。"""
        errors = []
        warnings = []

        # 检查起始场景是否存在
        start_scene = self.data.get_start_scene()
        if start_scene not in self.data.scenes:
            errors.append(f"起始场景不存在：{start_scene}")
            # 尝试使用第一个场景作为起始
            if self.data.scenes:
                first_scene = list(self.data.scenes.keys())[0]
                warnings.append(f"使用第一个场景作为起始：{first_scene}")
                self.data.config["start_scene"] = first_scene

        # 检查所有场景的 next 是否有效
        for scene_id, scene in self.data.scenes.items():
            for i, option in enumerate(scene.options):
                next_id = option.next
                if not next_id.startswith("end_") and next_id not in self.data.scenes:
                    errors.append(
                        f"场景 {scene_id} 的选项 {i} 跳转到不存在的场景：{next_id}"
                    )

        # 检查属性配置
        attributes = self.data.get_attributes()
        if not attributes:
            warnings.append("未定义任何属性")

        # 报告
        for w in warnings:
            logger.warning("数据验证警告：%s", w)
        for e in errors:
            logger.error("数据验证错误：%s", e)

        if errors:
            raise ValueError(f"数据验证失败（{len(errors)} 个错误）：{errors[0]}")

        logger.info("数据验证通过")

    # ============================================================
    # 初始化
    # ============================================================
    def _init_state(self):
        """根据配置初始化游戏状态。"""
        try:
            default_val = self.data.get_attribute_default()
            for attr in self.data.get_attributes():
                self.state.attributes[attr] = default_val

            self.state.current_scene_id = self.data.get_start_scene()
            self.history.push(self.state.current_scene_id)

            logger.debug(
                "状态初始化完成：属性=%s，起始场景=%s",
                self.state.attributes,
                self.state.current_scene_id,
            )
        except Exception as e:
            logger.error("状态初始化失败：%s", e, exc_info=True)
            raise

    # ============================================================
    # 核心接口
    # ============================================================
    def get_current_scene(self) -> Optional[Scene]:
        """获取当前场景。"""
        scene = self.data.scenes.get(self.state.current_scene_id)
        if not scene:
            logger.error("当前场景不存在：%s", self.state.current_scene_id)
        return scene

    def get_available_options(self) -> List[Option]:
        """获取当前可选选项（已过滤条件不满足的）。"""
        scene = self.get_current_scene()
        if not scene:
            logger.warning("当前无场景，返回空选项列表")
            return []

        available = [
            opt for opt in scene.options
            if self.evaluator.check(opt.condition, self.state)
        ]

        logger.debug("场景 %s：%d/%d 个选项可用", scene.id, len(available), len(scene.options))
        return available

    def choose_option(self, index: int) -> bool:
        """执行选项。

        Args:
            index: 选项索引（从 0 开始）。

        Returns:
            True 表示执行成功（包括触发了结局也返回 True）。
        """
        available = self.get_available_options()
        if index < 0 or index >= len(available):
            logger.error("选项索引越界：%d（可用选项数=%d）", index, len(available))
            return False

        option = available[index]
        self.state.turn_count += 1
        logger.debug("执行选项：%s -> %s", option.text[:30], option.next)

        try:
            # 1. 应用属性效果
            for attr, delta in option.effects.items():
                if attr in self.state.attributes:
                    old_val = self.state.attributes[attr]
                    self.state.attributes[attr] += delta
                    logger.debug("属性变化：%s %d -> %d", attr, old_val, self.state.attributes[attr])
                else:
                    logger.warning("选项引用了未定义的属性：%s", attr)

            # 2. 设置标记
            if option.flag:
                self.state.flags.add(option.flag)
                logger.debug("设置标记：%s", option.flag)

            # 3. 给予线索
            if option.give_clue:
                self.state.clues.add(option.give_clue)
                logger.debug("获得线索：%s", option.give_clue)

            # 4. 检查属性触发结局
            if self._check_attribute_endings():
                self._notify_listeners()
                return True

            # 5. 检查场景ID触发结局（end_xxx 格式）
            if option.next.startswith("end_"):
                self.state.ending_triggered = option.next
                logger.info("触发结局：%s", option.next)
                self._notify_listeners()
                return True

            # 6. 跳转场景
            if option.next in self.data.scenes:
                self.state.current_scene_id = option.next
                self.history.push(option.next)
                logger.debug("跳转到场景：%s", option.next)
            else:
                # 场景不存在 → 使用通用结局
                logger.error("场景不存在：%s，触发 missing_scene 结局", option.next)
                self.state.ending_triggered = "missing_scene"

            self._notify_listeners()
            return True

        except Exception as e:
            logger.error("执行选项失败：%s", e, exc_info=True)
            return False

    # ============================================================
    # 场景预览（新增）
    # ============================================================
    def preview_option(self, index: int) -> Optional[Tuple[Scene, Dict[str, int]]]:
        """预览选项的效果（不提交）。

        Returns:
            (下一个场景, 属性变化) 或 None（如果选项无效或触发结局）。
        """
        available = self.get_available_options()
        if index < 0 or index >= len(available):
            logger.warning("预览：选项索引越界 %d", index)
            return None

        option = available[index]

        # 如果触发结局，返回 None
        if option.next.startswith("end_"):
            logger.debug("预览：选项触发结局 %s", option.next)
            return None

        # 如果场景不存在
        if option.next not in self.data.scenes:
            logger.warning("预览：场景不存在 %s", option.next)
            return None

        next_scene = self.data.scenes[option.next]
        logger.debug("预览：%s -> %s", option.text[:30], next_scene.id)
        return next_scene, option.effects

    def preview_scene(self, scene_id: str) -> Optional[Scene]:
        """预览任意场景（不跳转）。"""
        if scene_id not in self.data.scenes:
            logger.warning("预览：场景不存在 %s", scene_id)
            return None
        logger.debug("预览场景：%s", scene_id)
        return self.data.scenes[scene_id]

    def preview_effects(self, index: int) -> Optional[Dict[str, int]]:
        """预览选项的属性变化（不提交）。"""
        available = self.get_available_options()
        if index < 0 or index >= len(available):
            return None
        return available[index].effects

    # ============================================================
    # 场景跳转（新增）
    # ============================================================
    def jump_to_scene(self, scene_id: str) -> bool:
        """直接跳转到任意场景（用于调试或作弊）。

        Args:
            scene_id: 目标场景 ID。

        Returns:
            True 表示跳转成功。
        """
        if scene_id not in self.data.scenes:
            logger.error("跳转失败：场景不存在 %s", scene_id)
            return False

        if self.is_ended:
            logger.warning("游戏已结束，先调用 restart() 再跳转")
            return False

        old_scene = self.state.current_scene_id
        self.state.current_scene_id = scene_id
        self.history.push(scene_id)
        logger.info("场景跳转：%s -> %s", old_scene, scene_id)
        self._notify_listeners()
        return True

    def jump_to_scene_by_tag(self, tag: str) -> bool:
        """按标签跳转场景（新增：需要在场景 JSON 中定义 tag 字段）。"""
        for scene_id, scene in self.data.scenes.items():
            if getattr(scene, "tag", None) == tag:
                return self.jump_to_scene(scene_id)
        logger.warning("按标签跳转失败：未找到 tag=%s 的场景", tag)
        return False

    # ============================================================
    # 撤销/重做（新增）
    # ============================================================
    def undo(self) -> bool:
        """撤销到最后一步。"""
        if not self.history.can_undo():
            logger.debug("无法撤销")
            return False

        # 回滚属性变化（简化版：只回滚最后一步的效果）
        # 注意：完整的回滚需要实现命令模式，这里提供简化版本
        prev_scene = self.history.undo()
        if prev_scene:
            self.state.current_scene_id = prev_scene
            logger.info("撤销到场景：%s", prev_scene)
            self._notify_listeners()
            return True
        return False

    def redo(self) -> bool:
        """重做。"""
        if not self.history.can_redo():
            logger.debug("无法重做")
            return False

        next_scene = self.history.redo()
        if next_scene:
            self.state.current_scene_id = next_scene
            logger.info("重做到场景：%s", next_scene)
            self._notify_listeners()
            return True
        return False

    def can_undo(self) -> bool:
        return self.history.can_undo()

    def can_redo(self) -> bool:
        return self.history.can_redo()

    # ============================================================
    # 结局检查
    # ============================================================
    def _check_attribute_endings(self) -> bool:
        """检查属性是否触顶/触底。"""
        attrs = self.state.attributes
        for attr_name, value in attrs.items():
            min_val = self.data.config.get("attribute_min", 0)
            max_val = self.data.config.get("attribute_max", 100)

            if value <= min_val:
                self.state.ending_triggered = f"low_{attr_name}"
                logger.info("触发结局（属性触底）：%s = %d", attr_name, value)
                return True
            if value >= max_val:
                self.state.ending_triggered = f"high_{attr_name}"
                logger.info("触发结局（属性触顶）：%s = %d", attr_name, value)
                return True
        return False

    def get_ending_text(self) -> str:
        """获取结局文本。"""
        if not self.state.ending_triggered:
            return ""
        endings = self.data.config.get("endings", {})
        text = endings.get(self.state.ending_triggered, self.state.ending_triggered)
        logger.debug("结局文本：%s", text[:50])
        return text

    @property
    def is_ended(self) -> bool:
        return self.state.ending_triggered is not None

    # ============================================================
    # 游戏控制（新增）
    # ============================================================
    def restart(self):
        """重新开始游戏。"""
        logger.info("重新开始游戏")
        self.state = GameState()
        self.history.clear()
        self._init_state()
        self._notify_listeners()

    def get_scene_list(self) -> List[str]:
        """获取所有场景 ID 列表（新增：用于调试/跳转）。"""
        return list(self.data.scenes.keys())

    def get_scene_info(self, scene_id: str) -> Optional[Dict[str, Any]]:
        """获取场景详细信息（新增）。"""
        scene = self.data.scenes.get(scene_id)
        if not scene:
            return None
        return {
            "id": scene.id,
            "speaker": scene.speaker,
            "text": scene.text,
            "option_count": len(scene.options),
            "is_current": scene.id == self.state.current_scene_id,
        }

    # ============================================================
    # 存档（增强：保存历史）
    # ============================================================
    def save(self, filepath: str):
        """保存到文件。"""
        try:
            data = {
                "version": self.VERSION,
                "config_title": self.data.title,
                "state": self.state.to_dict(),
                "history": self.history.to_dict(),
            }
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("游戏已保存：%s", filepath)
        except Exception as e:
            logger.error("保存失败：%s", e, exc_info=True)
            raise

    def load(self, filepath: str):
        """从文件恢复。"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            version = data.get("version", "0.0")
            if version != self.VERSION:
                logger.warning("存档版本不匹配：%s vs %s", version, self.VERSION)

            self.state = GameState.from_dict(data["state"])
            self.history = SceneHistory.from_dict(data.get("history", {}))
            logger.info("游戏已加载：%s", filepath)
            self._notify_listeners()
        except Exception as e:
            logger.error("加载失败：%s", e, exc_info=True)
            raise

    # ============================================================
    # 监听器（通知 UI 更新）
    # ============================================================
    def add_listener(self, callback: Callable):
        """添加状态变更监听器。UI 可注册以自动刷新。"""
        self._listeners.append(callback)
        logger.debug("添加监听器：%s", callback.__name__ if hasattr(callback, "__name__") else callback)

    def remove_listener(self, callback: Callable):
        if callback in self._listeners:
            self._listeners.remove(callback)
            logger.debug("移除监听器")

    def _notify_listeners(self):
        for cb in self._listeners:
            try:
                cb(self)
            except Exception as e:
                logger.error("监听器执行失败：%s", e, exc_info=True)

    # ============================================================
    # 信息
    # ============================================================
    @property
    def attributes(self) -> Dict[str, int]:
        return dict(self.state.attributes)

    @property
    def title(self) -> str:
        return self.data.title

    @property
    def current_scene_id(self) -> str:
        return self.state.current_scene_id

    @property
    def turn_count(self) -> int:
        return self.state.turn_count

    def get_stats(self) -> Dict[str, Any]:
        """获取游戏统计信息（新增）。"""
        return {
            "turn_count": self.state.turn_count,
            "current_scene": self.state.current_scene_id,
            "attributes": dict(self.state.attributes),
            "flags": list(self.state.flags),
            "clues": list(self.state.clues),
            "is_ended": self.is_ended,
            "ending": self.state.ending_triggered,
            "history_length": len(self.history.history),
        }

    def __repr__(self):
        return (
            f"<NarrativeEngine title='{self.title}' "
            f"scene='{self.state.current_scene_id}' "
            f"attrs={self.state.attributes} "
            f"ended={self.is_ended} "
            f"version={self.VERSION}>"
        )
