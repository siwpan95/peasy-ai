# -*- coding: utf-8 -*-
"""
迷失之镜 — 场景结算 + 回复机制 (ViewModel↔Model 层 · 阶段 5.5)
每解决一个主要挑战后，触发标准化结算流程
"""
from typing import Dict, Optional
from core.character import Character


class SceneResolver:
    """场景结算器"""

    def __init__(self):
        pass

    def resolve(self, node_result: Dict, pc: Character, node: Dict) -> Dict:
        """
        场景结算
        返回 rewards: {"focus_restored": int, "marks_healed": int, "xp": int}
        """
        rewards = {"focus_restored": 0, "marks_healed": 0, "xp": 0, "narrative": ""}

        # 1. 专注点回复
        if node_result.get("is_major_challenge", True):
            # 每个主要挑战回复 1 专注点
            if pc.focus_points < pc.focus_max:
                pc.recover_focus(1)
                rewards["focus_restored"] = 1

        if node_result.get("is_safe_node", False):
            # 安全节点补满专注点
            restored = pc.focus_max - pc.focus_points
            pc.focus_points = pc.focus_max
            rewards["focus_restored"] = restored

            # 安全节点可消减印记
            if pc.psychic_marks > 0:
                pc.psychic_marks = max(0, pc.psychic_marks - 1)
                rewards["marks_healed"] = 1

        # 2. 永久执念检查
        if pc.psychic_marks >= 3 and not pc.has_obsession:
            pc.has_obsession = True
            pc.obsession_name = "镜痴"
            pc.permanent_tags.append("镜痴:对抗镜子相关检定 Will-2")
            rewards["narrative"] = "你开始听到镜子里的低语……某些东西正在你的灵魂深处扎根。"

        # 3. XP 基础奖励（每场景 1 点）
        rewards["xp"] = 1

        return rewards

    def safe_node_recovery(self, pc: Character) -> Dict:
        """安全节点完整恢复"""
        rewards = {"focus_restored": 0, "marks_healed": 0}

        # 专注点回满
        restored = pc.focus_max - pc.focus_points
        pc.focus_points = pc.focus_max
        rewards["focus_restored"] = restored

        # 印记消 1
        if pc.psychic_marks > 0:
            pc.psychic_marks -= 1
            rewards["marks_healed"] = 1

        return rewards
