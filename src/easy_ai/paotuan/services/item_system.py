# -*- coding: utf-8 -*-
"""
迷失之镜 — 物品/装备运行时系统 (Model 层 · 阶段 2.5)
处理装备装备、卸下、使用消耗品、DR 统计、物品交互
"""
import random
from typing import List, Dict, Optional, Tuple
try:
    from ..core.character import Character, Equipment
except ImportError:  # 脚本自举模式（sys.path[0] = paotuan/ 目录）
    from core.character import Character, Equipment


class ItemSystem:
    """物品运行时管理器"""

    def __init__(self, items_db: Dict = None):
        self.items_db = items_db or {}  # 物品模板库

    def load_items(self, path: str):
        """从 JSON 加载物品库"""
        import json
        with open(path, "r", encoding="utf-8") as f:
            self.items_db = json.load(f)

    def create_item(self, item_id: str) -> Optional[Equipment]:
        """从模板创建物品实例"""
        template = self.items_db.get(item_id)
        if not template:
            return None
        return Equipment(
            name=template.get("name", item_id),
            etype=template.get("type", "misc"),
            slot=template.get("slot", ""),
            damage=template.get("damage", ""),
            dr=template.get("dr", 0),
            dr_location=template.get("dr_location", ""),
            effects=template.get("effects", []),
            uses=template.get("uses", -1),
            penalty=template.get("penalty", {}),
            description=template.get("description", ""),
        )

    def equip(self, pc: Character, item: Equipment) -> Tuple[bool, str]:
        """装备物品"""
        if item.slot:
            # 检查同槽位冲突
            for eq in pc.equipment:
                if eq.equipped and eq.slot == item.slot and eq.slot != "backpack":
                    eq.equipped = False  # 卸下旧物品
        item.equipped = True
        return True, f"装备了 {item.name}"

    def unequip(self, pc: Character, item: Equipment) -> Tuple[bool, str]:
        """卸下物品"""
        item.equipped = False
        return True, f"卸下了 {item.name}"

    def use_consumable(self, pc: Character, item: Equipment) -> Tuple[bool, str]:
        """使用消耗品"""
        if item.etype != "consumable":
            return False, f"{item.name} 不是消耗品"
        if item.uses == 0:
            return False, f"{item.name} 已耗尽"

        result_parts = []
        for effect in item.effects:
            if "restore_hp" in effect:
                dice = effect["restore_hp"]
                amount = self._roll_dice(dice)
                pc.hp = min(pc.hp_max, pc.hp + amount)
                result_parts.append(f"回复 {amount} HP")
            if "remove_tag" in effect:
                pc.remove_tag(effect["remove_tag"])
                result_parts.append(f"移除标签「{effect['remove_tag']}」")

        if item.uses > 0:
            item.uses -= 1
        return True, f"使用 {item.name}: " + ", ".join(result_parts)

    def check_item_mitigation(self, pc: Character, item_check: dict) -> Optional[str]:
        """检查玩家是否携带可缓解场景否效果的物品"""
        required_item = item_check.get("item_mitigation", {})
        for item_id, mitigation_desc in required_item.items():
            for eq in pc.equipment:
                if eq.equipped and eq.name == item_id:
                    return mitigation_desc
        return None

    def get_active_item_effects(self, pc: Character) -> List[Dict]:
        """获取所有装备物品的活跃效果"""
        effects = []
        for eq in pc.equipment:
            if eq.equipped and eq.effects:
                for ef in eq.effects:
                    effects.append({**ef, "source": eq.name})
        return effects

    @staticmethod
    def _roll_dice(dice_str: str) -> int:
        """解析并掷骰子。格式: '1d6' / '2d4+1' / '1d3'"""
        import re
        match = re.match(r"(\d+)d(\d+)([+-]\d+)?", dice_str)
        if not match:
            return 0
        count, sides = int(match.group(1)), int(match.group(2))
        modifier = int(match.group(3) or 0)
        total = sum(random.randint(1, sides) for _ in range(count))
        return total + modifier
