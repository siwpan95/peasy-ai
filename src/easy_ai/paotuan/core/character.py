# -*- coding: utf-8 -*-
"""
迷失之镜 — Character 数据类 (Model 层)
GURPS 100点角色模型：四属性 + 衍生值 + 技能 + 优劣势 + 特征 + 装备
"""
import json
import copy
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class CharacterFeature:
    """角色特征（叙事层）—— 触发-响应模式"""
    name: str
    trigger_condition: str  # 触发条件描述
    cost: int = 1  # 专注点消耗
    effect: str = ""  # 响应动作
    per_scene_limit: int = 1  # 每场景可用次数
    used_this_scene: int = 0  # 当前场景已使用次数


@dataclass
class Equipment:
    """装备"""
    name: str
    etype: str = "misc"  # weapon / armor / tool / consumable / key_item
    slot: str = ""  # hand / body / head / ring / backpack
    damage: str = ""  # "2d6 pi+" or ""
    dr: int = 0  # 护甲值
    dr_location: str = ""  # torso / head / full / arms / legs
    effects: List[Dict] = field(default_factory=list)  # {"tag_mod":"remove:低能见度", "range":"5m"}
    uses: int = -1  # -1=无限
    penalty: Dict = field(default_factory=dict)  # {"dx": -1} 等
    equipped: bool = False
    description: str = ""


@dataclass
class Skill:
    """技能"""
    name: str
    level: int  # 最终等级
    difficulty: str = "Avg"  # Easy / Avg / Hard / VH
    base_attribute: str = "DX"  # ST / DX / IQ / HT
    points_spent: int = 0
    notes: str = ""


@dataclass
class Character:
    """GURPS 角色数据模型 (Model 层)"""
    # === 元信息 ===
    character_id: str = ""
    name: str = "未命名"
    version: int = 1
    previous_version: str = ""

    # === 属性 (100点起手) ===
    st: int = 10
    dx: int = 10
    iq: int = 10
    ht: int = 10

    # === 衍生值 ===
    hp: int = 10
    hp_max: int = 10
    fp: int = 10
    fp_max: int = 10
    will: int = 10
    per: int = 10

    # === 技能 ===
    skills: List[Skill] = field(default_factory=list)

    # === 优势/劣势 ===
    advantages: List[str] = field(default_factory=list)
    disadvantages: List[str] = field(default_factory=list)

    # === 叙事层 ===
    features: List[CharacterFeature] = field(default_factory=list)
    focus_points: int = 3
    focus_max: int = 3
    luck_points: int = 2
    luck_max: int = 2
    psychic_marks: int = 0
    anchors: List[str] = field(default_factory=list)  # 角色的锚定物

    # === 装备 ===
    equipment: List[Equipment] = field(default_factory=list)

    # === 运行时状态 ===
    permanent_tags: List[str] = field(default_factory=list)  # 永久标签（如镜痴）
    temporary_tags: List[Dict] = field(default_factory=list)  # 临时标签 {"name":"行动力受损:左臂","modifier":-2,"duration":...}
    has_obsession: bool = False
    obsession_name: str = ""

    # === 成长 ===
    xp_log: List[Dict] = field(default_factory=list)
    total_xp: int = 0

    @property
    def dodge(self) -> int:
        """计算闪避值"""
        d = (self.dx + 2) // 2
        # 装备惩罚
        for eq in self.equipment:
            if eq.equipped and eq.penalty:
                d += int(eq.penalty.get("dx", 0))
        # 临时标签修正
        for tag in self.temporary_tags:
            if "dodge" in tag.get("effect", "").lower() or "闪避" in tag.get("name", ""):
                d += int(tag.get("modifier", 0))
        return max(0, d)

    @property
    def shock_threshold(self) -> int:
        """休克阈值"""
        return max(1, self.hp_max // 3)

    def get_skill_level(self, skill_name: str) -> Optional[int]:
        """查找技能等级"""
        for s in self.skills:
            if s.name == skill_name:
                return s.level
        # 回退到基础属性
        attr_map = {"ST": self.st, "DX": self.dx, "IQ": self.iq, "HT": self.ht}
        for attr_name, attr_val in attr_map.items():
            if skill_name.upper() == attr_name:
                return attr_val
        return None

    def get_total_dr(self, location: str) -> int:
        """计算指定部位的 DR"""
        total = 0
        for eq in self.equipment:
            if eq.equipped and eq.dr > 0:
                loc = eq.dr_location or "full"
                if loc == "full" or location in loc:
                    total += eq.dr
        return total

    def get_equipped_weapons(self) -> List[Equipment]:
        """获取当前装备的武器"""
        return [e for e in self.equipment if e.equipped and e.etype == "weapon"]

    def add_tag(self, name: str, modifier: int = 0, duration: str = "scene"):
        """添加临时标签"""
        self.temporary_tags.append({
            "name": name,
            "modifier": modifier,
            "duration": duration,
        })

    def remove_tag(self, name: str):
        """移除标签"""
        self.temporary_tags = [t for t in self.temporary_tags if t["name"] != name]

    def calc_tag_modifier(self) -> int:
        """汇总所有标签的检定修正"""
        return sum(int(t.get("modifier", 0)) for t in self.temporary_tags)

    def spend_fp(self, amount: int = 1):
        """消耗 FP"""
        self.fp -= amount
        if self.fp < 0:
            self.hp += self.fp  # FP 负数转为扣 HP
            self.fp = 0

    def spend_focus(self, amount: int = 1) -> bool:
        """消耗专注点"""
        if self.focus_points >= amount:
            self.focus_points -= amount
            return True
        return False

    def spend_luck(self, amount: int = 1) -> bool:
        """消耗幸运点"""
        if self.luck_points >= amount:
            self.luck_points -= amount
            return True
        return False

    def recover_focus(self, amount: int = 1):
        """回复专注点（不超过上限）"""
        self.focus_points = min(self.focus_max, self.focus_points + amount)

    def add_psychic_mark(self, count: int = 1):
        """增加精神印记并检查崩溃"""
        self.psychic_marks += count
        if self.psychic_marks >= 3 and not self.has_obsession:
            self.has_obsession = True
            self.obsession_name = "镜痴"
            self.permanent_tags.append("镜痴:对抗镜子相关检定 Will-2")

    def create_snapshot(self) -> dict:
        """创建角色快照（用于存档）"""
        return {
            "character_id": self.character_id,
            "name": self.name,
            "version": self.version,
            "hp": self.hp, "hp_max": self.hp_max,
            "fp": self.fp, "fp_max": self.fp_max,
            "will": self.will, "per": self.per,
            "focus_points": self.focus_points, "focus_max": self.focus_max,
            "luck_points": self.luck_points, "luck_max": self.luck_max,
            "psychic_marks": self.psychic_marks,
            "temporary_tags": copy.deepcopy(self.temporary_tags),
            "has_obsession": self.has_obsession,
            "obsession_name": self.obsession_name,
            "permanent_tags": list(self.permanent_tags),
        }

    def restore_snapshot(self, snapshot: dict):
        """从存档快照恢复运行时状态"""
        self.hp = snapshot.get("hp", self.hp)
        self.hp_max = snapshot.get("hp_max", self.hp_max)
        self.fp = snapshot.get("fp", self.fp)
        self.fp_max = snapshot.get("fp_max", self.fp_max)
        self.will = snapshot.get("will", self.will)
        self.per = snapshot.get("per", self.per)
        self.focus_points = snapshot.get("focus_points", self.focus_points)
        self.focus_max = snapshot.get("focus_max", self.focus_max)
        self.luck_points = snapshot.get("luck_points", self.luck_points)
        self.luck_max = snapshot.get("luck_max", self.luck_max)
        self.psychic_marks = snapshot.get("psychic_marks", self.psychic_marks)
        self.temporary_tags = copy.deepcopy(snapshot.get("temporary_tags", []))
        self.has_obsession = snapshot.get("has_obsession", False)
        self.obsession_name = snapshot.get("obsession_name", "")
        self.permanent_tags = list(snapshot.get("permanent_tags", []))

    def to_dict(self) -> dict:
        """完整序列化"""
        return {
            "character_id": self.character_id,
            "name": self.name,
            "version": self.version,
            "previous_version": self.previous_version,
            "attributes": {"ST": self.st, "DX": self.dx, "IQ": self.iq, "HT": self.ht},
            "secondary": {"HP": self.hp_max, "FP": self.fp_max, "Will": self.will, "Per": self.per},
            "skills": [{"name": s.name, "level": s.level, "difficulty": s.difficulty,
                         "base_attribute": s.base_attribute, "points_spent": s.points_spent,
                         "notes": s.notes} for s in self.skills],
            "advantages": self.advantages,
            "disadvantages": self.disadvantages,
            "features": [{"name": f.name, "trigger_condition": f.trigger_condition,
                           "cost": f.cost, "effect": f.effect,
                           "per_scene_limit": f.per_scene_limit} for f in self.features],
            "anchors": self.anchors,
            "equipment": [{"name": e.name, "type": e.etype, "slot": e.slot,
                            "damage": e.damage, "dr": e.dr, "dr_location": e.dr_location,
                            "effects": e.effects, "uses": e.uses, "penalty": e.penalty,
                            "description": e.description} for e in self.equipment],
            "focus_max": self.focus_max,
            "luck_max": self.luck_max,
            "xp_log": self.xp_log,
            "total_xp": self.total_xp,
        }

    def to_json(self, path: str):
        """保存角色到 JSON 文件"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "Character":
        """从字典创建角色"""
        attrs = data.get("attributes", {})
        sec = data.get("secondary", {})
        c = cls(
            character_id=data.get("character_id", ""),
            name=data.get("name", "未命名"),
            version=data.get("version", 1),
            previous_version=data.get("previous_version", ""),
            st=attrs.get("ST", 10), dx=attrs.get("DX", 10),
            iq=attrs.get("IQ", 10), ht=attrs.get("HT", 10),
            hp=sec.get("HP", 10), hp_max=sec.get("HP", 10),
            fp=sec.get("FP", 10), fp_max=sec.get("FP", 10),
            will=sec.get("Will", 10), per=sec.get("Per", 10),
            advantages=data.get("advantages", []),
            disadvantages=data.get("disadvantages", []),
            anchors=data.get("anchors", []),
            focus_max=data.get("focus_max", 3),
            focus_points=data.get("focus_max", 3),
            luck_max=data.get("luck_max", 2),
            luck_points=data.get("luck_max", 2),
            xp_log=data.get("xp_log", []),
            total_xp=data.get("total_xp", 0),
        )
        # 技能
        for s in data.get("skills", []):
            c.skills.append(Skill(
                name=s["name"], level=s["level"],
                difficulty=s.get("difficulty", "Avg"),
                base_attribute=s.get("base_attribute", "DX"),
                points_spent=s.get("points_spent", 0),
                notes=s.get("notes", ""),
            ))
        # 特征
        for f in data.get("features", []):
            c.features.append(CharacterFeature(
                name=f["name"], trigger_condition=f["trigger_condition"],
                cost=f.get("cost", 1), effect=f.get("effect", ""),
                per_scene_limit=f.get("per_scene_limit", 1),
            ))
        # 装备
        for e in data.get("equipment", []):
            c.equipment.append(Equipment(
                name=e["name"], etype=e.get("type", "misc"),
                slot=e.get("slot", ""), damage=e.get("damage", ""),
                dr=e.get("dr", 0), dr_location=e.get("dr_location", ""),
                effects=e.get("effects", []), uses=e.get("uses", -1),
                penalty=e.get("penalty", {}), description=e.get("description", ""),
            ))
        return c

    @classmethod
    def from_json(cls, path: str) -> "Character":
        """从 JSON 文件加载角色"""
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
