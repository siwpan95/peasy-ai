# -*- coding: utf-8 -*-
"""
迷失之镜 — 环境系统 (Model↔ViewModel 层 · 阶段 3.5)
环境即第一 NPC —— 持续产出标签，玩家可花费专注点改变环境
"""
from typing import List, Dict, Optional


class EnvironmentSystem:
    """环境运行时系统"""

    def __init__(self):
        self.tags: List[Dict] = []  # [{"name":"暴雨湿滑","modifier":-2,"duration":"scene","active":True}]
        self.ambient_narrative: str = ""
        self.pending_changes: List[Dict] = []  # VM 产出的环境变化

    def load_tags(self, tags_config: List[Dict]):
        """从 module.json 加载环境标签"""
        self.tags = []
        for tag in tags_config:
            self.tags.append({
                "name": tag.get("name", ""),
                "effect": tag.get("effect", ""),
                "modifier": self._parse_modifier(tag.get("effect", "")),
                "active": True,
                "duration": "scene",
                "progression": tag.get("progression", None),  # 渐进恶化配置
            })

    def _parse_modifier(self, effect_str: str) -> int:
        """从效果文本解析修正值"""
        # 简单解析: "闪避 -1，攀爬 -2" → 取第一个负数的平均
        import re
        numbers = re.findall(r'[-]?\d+', effect_str)
        if numbers:
            return sum(int(n) for n in numbers) // len(numbers)
        return 0

    def get_active_modifiers(self) -> int:
        """汇总当前所有环境标签的检定修正"""
        total = 0
        for tag in self.tags:
            if tag.get("active", True):
                total += tag.get("modifier", 0)
        return total

    def get_tag_names(self) -> List[str]:
        """获取当前活跃标签名列表"""
        return [t["name"] for t in self.tags if t.get("active", True)]

    def on_scene_enter(self, node: Dict):
        """进入新场景 → 加载环境标签"""
        env = node.get("environment", {})
        if env.get("tags"):
            self.load_tags(env["tags"])
        self.ambient_narrative = env.get("mood", "")

        # 也处理环境更新指令
        env_update = node.get("environment_update", {})
        if env_update:
            for tag_id in env_update.get("remove_tags", []):
                self.remove_tag_by_id(tag_id)
            for tag_config in env_update.get("add_tags", []):
                self.add_tag(tag_config.get("name", ""),
                             self._parse_modifier(tag_config.get("effect", "")),
                             tag_config.get("duration", "scene"))

    def on_scene_tick(self):
        """每回合/每次行动 → 环境自发变化"""
        for tag in self.tags:
            progression = tag.get("progression")
            if progression:
                tag["modifier"] += progression.get("increase_per_tick", 0)

    def add_tag(self, name: str, modifier: int = 0, duration: str = "scene"):
        """添加环境标签"""
        # 检查重复
        for tag in self.tags:
            if tag["name"] == name:
                tag["modifier"] = modifier
                tag["active"] = True
                return
        self.tags.append({
            "name": name,
            "modifier": modifier,
            "active": True,
            "duration": duration,
        })

    def remove_tag(self, name: str):
        """按名称移除标签"""
        self.tags = [t for t in self.tags if t["name"] != name]

    def remove_tag_by_id(self, tag_id: str):
        """按 ID 移除标签"""
        self.tags = [t for t in self.tags if t.get("id", "") != tag_id]

    def clear_one_shot_tags(self):
        """清除一次性标签"""
        self.tags = [t for t in self.tags if t.get("duration") != "oneshot"]

    def resolve_environment_update(self, vm_update: Dict):
        """应用 ViewModel 产出的环境更新"""
        if not vm_update:
            return
        for tag_name in vm_update.get("removed_tags", []):
            self.remove_tag(tag_name)
        for tag_config in vm_update.get("added_tags", []):
            if isinstance(tag_config, str):
                self.add_tag(tag_config)
            else:
                self.add_tag(
                    tag_config.get("name", ""),
                    tag_config.get("modifier", 0),
                    tag_config.get("duration", "scene"),
                )

    def player_focus_action(self, action: str) -> Optional[str]:
        """玩家花 ○ 改变环境，返回叙事描述"""
        if action == "create_light":
            self.remove_tag("低能见度:黑暗")
            self.add_tag("临时光源", modifier=0, duration="3 rounds")
            return "你点燃了手边的光源，黑暗暂时退却了。"
        if action == "kick_debris":
            self.add_tag("声学暴露", modifier=-2, duration="this scene")
            return "你踢开杂物——巨大的回响在空间中荡开，任何在暗处的东西都知道你来了。"
        return None

    def to_dict(self) -> dict:
        return {
            "tags": self.tags,
            "ambient_narrative": self.ambient_narrative,
        }
