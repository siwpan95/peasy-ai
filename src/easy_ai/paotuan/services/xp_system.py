# -*- coding: utf-8 -*-
"""
迷失之镜 — XP / 角色成长系统 (Model 层 · 阶段 6.5)
GURPS char points 发放 + 角色升级
"""
from typing import Dict, List
try:
    from ..core.character import Character, Skill
except ImportError:  # 脚本自举模式（sys.path[0] = paotuan/ 目录）
    from core.character import Character, Skill


class XPSystem:
    """角色成长系统"""

    def calculate_xp(self, completed_scenes: int, flags_count: int,
                     psychic_marks: int, base_xp: int = 3) -> int:
        """
        计算 XP 奖励
        - 每个完成场景 1 点
        - 模组基础奖励 (默认 3)
        - 每 3 个 flag = 1 点
        - 有印记（精神体验） +1
        """
        xp = 0
        xp += completed_scenes
        xp += base_xp
        xp += flags_count // 3
        xp += 1 if psychic_marks > 0 else 0
        return xp

    def apply_xp(self, character: Character, xp: int):
        """将 XP 存入角色"""
        character.total_xp += xp
        character.xp_log.append({
            "earned": xp,
            "timestamp": "",
            "spent": {},
        })

    def spend_xp(self, character: Character, category: str, target: str, amount: int) -> bool:
        """
        分配 XP 到属性/技能
        价格：属性 ST/HT $10, DX/IQ $20
              技能 Easy $1, Avg $2, Hard $4, VH $8
        """
        cost_table = {
            "ST": 10, "DX": 20, "IQ": 20, "HT": 10,
        }

        if category == "attribute":
            cost = cost_table.get(target, 10)
            if character.total_xp >= cost * amount:
                character.total_xp -= cost * amount
                setattr(character, target.lower(), getattr(character, target.lower()) + amount)
                return True
            return False

        elif category == "skill":
            return False  # 暂不实现 XP 购买技能

        return False

    def version_up(self, character: Character):
        """版本升级"""
        character.previous_version = f"{character.character_id}_v{character.version}"
        character.version += 1

    def get_upgrade_options(self, character: Character) -> List[Dict]:
        """获取可用升级选项"""
        options = []

        # 属性升级
        for attr in ["ST", "DX", "IQ", "HT"]:
            cost = 10 if attr in ("ST", "HT") else 20
            if character.total_xp >= cost:
                options.append({
                    "category": "attribute",
                    "target": attr,
                    "cost": cost,
                    "current": getattr(character, attr.lower()),
                    "description": f"提升 {attr} 到 {getattr(character, attr.lower()) + 1}（{cost} XP）",
                })

        return options
