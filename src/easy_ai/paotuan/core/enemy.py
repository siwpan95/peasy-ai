# -*- coding: utf-8 -*-
"""
迷失之镜 — Enemy 数据类 (Model 层)
支持附庸/精英/Wildcard/Boss 四种敌人类型
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class Enemy:
    """敌人数据模型"""
    name: str
    enemy_type: str = "mook"  # mook / elite / wildcard / boss

    # 属性
    st: int = 10
    dx: int = 10
    iq: int = 10
    ht: int = 10

    # 战斗属性
    hp: int = 10
    hp_max: int = 10
    fp: int = 10
    attack_skill: int = 12
    damage: str = "1d6 cut"  # 伤害骰表达式
    dodge: int = 8
    dr: int = 0
    parry: int = 0

    # 附庸阈值
    minion_threshold: Dict = field(default_factory=lambda: {
        ">=6": "立即移除",
        "2-5": "丧失行动力/溃逃",
        "<2": "轻微干扰",
    })

    # 特殊能力
    special_abilities: List[Dict] = field(default_factory=list)
    # e.g. {"name": "群扑", "effect": "Deceptive Attack -2 防御", "trigger": "attack"}

    # 叙事
    description: str = ""
    flavor_text: str = ""

    # 战利品
    loot_table: List[Dict] = field(default_factory=list)

    @property
    def is_mook(self) -> bool:
        return self.enemy_type == "mook"

    @property
    def is_wildcard(self) -> bool:
        return self.enemy_type == "wildcard"

    @property
    def shock_threshold(self) -> int:
        return max(1, self.hp_max // 3)

    def resolve_minion_damage(self, damage: int) -> str:
        """根据附庸伤害阈值返回结果"""
        if damage >= 6:
            return "removed"
        elif damage >= 2:
            return "disabled"
        return "minor"

    def clone(self) -> "Enemy":
        """快速复制（用于群敌）"""
        return Enemy(
            name=self.name, enemy_type=self.enemy_type,
            st=self.st, dx=self.dx, iq=self.iq, ht=self.ht,
            hp=self.hp, hp_max=self.hp_max, fp=self.fp,
            attack_skill=self.attack_skill, damage=self.damage,
            dodge=self.dodge, dr=self.dr, parry=self.parry,
            minion_threshold=dict(self.minion_threshold),
            special_abilities=list(self.special_abilities),
            description=self.description, flavor_text=self.flavor_text,
            loot_table=list(self.loot_table),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "enemy_type": self.enemy_type,
            "st": self.st, "dx": self.dx, "iq": self.iq, "ht": self.ht,
            "hp": self.hp, "hp_max": self.hp_max, "fp": self.fp,
            "attack_skill": self.attack_skill, "damage": self.damage,
            "dodge": self.dodge, "dr": self.dr, "parry": self.parry,
            "minion_threshold": self.minion_threshold,
            "special_abilities": self.special_abilities,
            "description": self.description, "flavor_text": self.flavor_text,
            "loot_table": self.loot_table,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Enemy":
        return cls(
            name=data.get("name", "未知敌人"),
            enemy_type=data.get("enemy_type", "mook"),
            st=data.get("st", 10), dx=data.get("dx", 10),
            iq=data.get("iq", 10), ht=data.get("ht", 10),
            hp=data.get("hp", 10), hp_max=data.get("hp_max", 10),
            fp=data.get("fp", 10),
            attack_skill=data.get("attack_skill", 12),
            damage=data.get("damage", "1d6 cut"),
            dodge=data.get("dodge", 8), dr=data.get("dr", 0),
            parry=data.get("parry", 0),
            minion_threshold=data.get("minion_threshold", {">=6": "removed", "2-5": "disabled", "<2": "minor"}),
            special_abilities=data.get("special_abilities", []),
            description=data.get("description", ""),
            flavor_text=data.get("flavor_text", ""),
            loot_table=data.get("loot_table", []),
        )
