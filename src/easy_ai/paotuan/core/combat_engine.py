# -*- coding: utf-8 -*-
"""
迷失之镜 — 战斗引擎 (Model 层 · 阶段 4)
倡议抽牌 + 附庸 + Wildcard + FP 休克 + 主动防御 + 部位伤害
"""
import random
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
try:
    from .character import Character
    from .enemy import Enemy
except ImportError:  # 脚本自举模式（sys.path[0] = paotuan/ 目录）
    from core.character import Character
    from core.enemy import Enemy


# === 命中部位表 ===
HIT_LOCATIONS = {
    3: "头", 4: "头", 5: "头",
    6: "右臂", 7: "左臂",
    8: "躯干", 9: "躯干", 10: "躯干", 11: "躯干",
    12: "右腿", 13: "左腿",
    14: "躯干", 15: "躯干", 16: "躯干",
    17: "头", 18: "头",
}


@dataclass
class CombatState:
    """单轮战斗状态"""
    round_num: int = 0
    participants: List[Dict] = field(default_factory=list)  # [{"name":..., "entity":..., "card":...}]
    initiative_order: List[str] = field(default_factory=list)
    current_actor_idx: int = 0
    combat_log: List[str] = field(default_factory=list)


class CombatEngine:
    """战斗引擎"""

    def __init__(self):
        self.state: Optional[CombatState] = None

    @staticmethod
    def roll_3d6() -> int:
        return sum(random.randint(1, 6) for _ in range(3))

    @staticmethod
    def roll_damage(damage_str: str) -> int:
        """掷伤害骰。格式: '1d6 cut' / '2d6+1 imp'"""
        import re
        match = re.match(r"(\d+)d(\d+)([+-]\d+)?", damage_str)
        if not match:
            return 1
        count, sides = int(match.group(1)), int(match.group(2))
        modifier = int(match.group(3) or 0)
        total = sum(random.randint(1, sides) for _ in range(count))
        return max(1, total + modifier)

    @staticmethod
    def get_damage_type(damage_str: str) -> str:
        """从伤害字符串提取类型"""
        if "cut" in damage_str.lower() or "切割" in damage_str:
            return "切割"
        if "imp" in damage_str.lower() or "穿刺" in damage_str or "pi" in damage_str.lower():
            return "穿刺"
        if "cr" in damage_str.lower() or "钝击" in damage_str:
            return "钝击"
        if "burn" in damage_str.lower() or "燃烧" in damage_str:
            return "燃烧"
        return "钝击"

    @staticmethod
    def roll_hit_location() -> str:
        """掷部位表"""
        roll = CombatEngine.roll_3d6()
        return HIT_LOCATIONS.get(roll, "躯干")

    # === 倡议 ===

    def draw_initiative(self, participants: List[Tuple[str, object]]) -> List[str]:
        """抽牌决定行动顺序"""
        cards = []
        for name, _ in participants:
            card = random.randint(1, 54)  # 模拟54张牌
            cards.append((name, card))
        cards.sort(key=lambda x: x[1], reverse=True)  # 高牌先动
        return [name for name, _ in cards]

    # === 战斗轮 ===

    def init_combat(self, pc: Character, enemies: List[Enemy]) -> CombatState:
        """初始化战斗"""
        state = CombatState(round_num=0)

        # 参与者：PC + 所有敌人
        participants = [("PC", pc)]
        for i, enemy in enumerate(enemies):
            tag = "Wildcard" if enemy.is_wildcard else "Mook"
            participants.append((f"{enemy.name}#{i+1}", enemy))

        state.participants = [
            {"name": name, "entity": ent, "card": random.randint(1, 54)}
            for name, ent in participants
        ]
        state.initiative_order = self.draw_initiative(participants)
        self.state = state
        return state

    def start_round(self):
        """开始新回合"""
        if not self.state:
            return
        self.state.round_num += 1
        # 重新抽牌
        participants = [(p["name"], p["entity"]) for p in self.state.participants
                        if self._entity_alive(p["entity"])]
        self.state.initiative_order = self.draw_initiative(participants)
        self.state.current_actor_idx = 0
        self.state.combat_log.append(f"--- 第 {self.state.round_num} 回合 ---")

    # === 攻击裁决 ===

    def attack_resolve(self, attacker, defender, attacker_skill: int,
                       is_reverse: bool = False) -> Dict:
        """
        攻击裁决
        返回裁决数据包: {success, roll, target, margin, damage, location, type, dr, penetrated}
        """
        roll = self.roll_3d6()
        target = attacker_skill
        success = roll <= target
        is_crit = roll <= 4
        is_fumble = roll >= 17

        result = {
            "success": success,
            "roll": roll,
            "target": target,
            "margin": target - roll,
            "is_crit": is_crit,
            "is_fumble": is_fumble,
            "damage": 0,
            "raw_damage": 0,
            "location": "躯干",
            "type": "钝击",
            "dr": 0,
            "penetrated": 0,
            "defender_name": getattr(defender, "name", "目标"),
        }

        if not success or is_fumble:
            return result

        # 命中部位
        location = self.roll_hit_location()
        result["location"] = location

        # 伤害
        if isinstance(attacker, Character):
            weapons = attacker.get_equipped_weapons()
            damage_str = weapons[0].damage if weapons else "1d6 cut"
        elif isinstance(attacker, Enemy):
            damage_str = attacker.damage
        else:
            damage_str = "1d6 cut"

        raw = self.roll_damage(damage_str)
        dtype = self.get_damage_type(damage_str)

        # 暴击双倍
        if is_crit:
            raw *= 2

        result["raw_damage"] = raw
        result["type"] = dtype

        # 防御方 DR
        if isinstance(defender, Character):
            dr = defender.get_total_dr(location)
        elif isinstance(defender, Enemy):
            dr = defender.dr
        else:
            dr = 0

        result["dr"] = dr
        penetrated = max(0, raw - dr)

        # 伤害类型倍率
        if dtype == "切割":
            penetrated = int(penetrated * 1.5)
        elif dtype == "穿刺" and raw > dr:
            penetrated = penetrated * 2

        result["damage"] = penetrated
        result["penetrated"] = penetrated

        # 部位效应
        location_effects = {}
        if "头" in location and penetrated >= 2:
            location_effects["shock"] = -4
        if "臂" in location and penetrated >= 3:
            location_effects["weapon_grip"] = -2
        if "腿" in location and penetrated >= 3:
            location_effects["movement"] = -2

        result["location_effects"] = location_effects

        return result

    def active_defense(self, defender, attack_packet: Dict) -> Dict:
        """
        主动防御判定（闪避）
        返回: {"result": "dodged"|"hit", "narrative": "..."}
        """
        if isinstance(defender, Character):
            dodge = defender.dodge
        elif isinstance(defender, Enemy):
            dodge = defender.dodge
        else:
            dodge = 8

        roll = self.roll_3d6()

        if roll <= dodge:
            return {"result": "dodged",
                    "narrative": "侧身闪过——攻击擦过衣角。",
                    "roll": roll, "dodge": dodge}

        return {"result": "hit",
                "narrative": "闪避失败——攻击命中！",
                "roll": roll, "dodge": dodge}

    # === 休克检定 ===

    def shock_check(self, entity, damage_taken: int) -> Dict:
        """HT 休克检定"""
        if isinstance(entity, Character):
            ht = entity.ht
            threshold = entity.shock_threshold
        elif isinstance(entity, Enemy):
            ht = entity.ht
            threshold = entity.shock_threshold
        else:
            return {"status": "ok"}

        if damage_taken < threshold:
            return {"status": "ok"}

        roll = self.roll_3d6()
        if roll > ht:
            return {"status": "stunned", "penalty": -4, "duration": "1 round"}

        return {"status": "ok"}

    # === 应用伤害 ===

    def apply_damage(self, target, packet: Dict, is_mook: bool = False) -> str:
        """应用伤害到目标，返回结果描述"""
        damage = packet["damage"]

        if isinstance(target, Character):
            target.hp -= damage
            # 休克检查
            shock = self.shock_check(target, damage)
            if shock["status"] == "stunned":
                target.add_tag("震慑", modifier=-4, duration="1 round")
                return "stunned"
            # 部位标签
            for effect_name, modifier in packet.get("location_effects", {}).items():
                target.add_tag(f"{effect_name}", modifier=modifier, duration="scene")
            return "damaged"

        elif isinstance(target, Enemy):
            if is_mook:
                result = target.resolve_minion_damage(damage)
                if result == "removed":
                    target.hp = 0
                elif result == "disabled":
                    target.hp = max(0, target.hp - damage)
                else:
                    target.hp = max(0, target.hp - min(damage, 2))
                return result
            else:
                target.hp -= damage
                shock = self.shock_check(target, damage)
                if shock["status"] == "stunned":
                    return "stunned"
                return "damaged"

        return "unknown"

    # === 辅助 ===

    def _entity_alive(self, entity) -> bool:
        if isinstance(entity, Character):
            return entity.hp > 0
        if isinstance(entity, Enemy):
            return entity.hp > 0
        return True

    def is_combat_over(self) -> bool:
        """检查战斗是否结束"""
        if not self.state:
            return True
        alive_pc = True
        alive_enemies = False
        for p in self.state.participants:
            if p["name"] == "PC":
                alive_pc = self._entity_alive(p["entity"])
            else:
                if self._entity_alive(p["entity"]):
                    alive_enemies = True
        return not alive_pc or not alive_enemies

    def get_pc_wins(self) -> Optional[bool]:
        """返回 PC 是否获胜 (None=还在进行)"""
        if not self.state:
            return None
        if not self.is_combat_over():
            return None
        for p in self.state.participants:
            if p["name"] == "PC" and self._entity_alive(p["entity"]):
                return True
        return False
