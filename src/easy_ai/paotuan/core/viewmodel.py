# -*- coding: utf-8 -*-
"""
迷失之镜 — ViewModel 转换管线 (ViewModel 层 · 阶段 5)
核心：裁决输出包 → 衍生状态位 → 叙事选项
MVVM 中间层 —— GURPS 的 "-4 HP, 切割, 左臂" 被翻译为 "刀刃划开前臂肌理"
"""
from typing import Dict, List, Optional, Any
try:
    from .character import Character
except ImportError:  # 脚本自举模式（sys.path[0] = paotuan/ 目录）
    from core.character import Character


class ViewModelResult:
    """ViewModel 输出结构"""
    def __init__(self):
        self.narrative: str = ""
        self.derived_tags: List[Dict] = []  # [{"name":"行动力受损:左臂","modifier":-2}]
        self.psychic_trigger: Optional[Dict] = None
        self.available_focus_actions: List[str] = []
        self.triggered_features: List[Dict] = []
        self.queued_events: List[Dict] = []
        self.choices: List[Dict] = []  # 提供给 View 层的选择项
        self.environment_update: Dict = {"added_tags": [], "removed_tags": [], "narrative": ""}
        self.status_changes: Dict = {}  # {"hp_delta": -4, "fp_delta": 0, "focus_delta": 0}

    def to_dict(self) -> dict:
        return {
            "narrative": self.narrative,
            "derived_tags": self.derived_tags,
            "psychic_trigger": self.psychic_trigger,
            "available_focus_actions": self.available_focus_actions,
            "triggered_features": self.triggered_features,
            "queued_events": self.queued_events,
            "choices": self.choices,
            "environment_update": self.environment_update,
            "status_changes": self.status_changes,
        }


class ViewModel:
    """
    ViewModel 转换层
    负责将 Model 层的原始裁决结果翻译为叙事文本 + 衍生状态
    """

    def __init__(self, anchor_library: Dict = None):
        self.anchor_library = anchor_library or {}  # 锚点短语库

    def load_anchors(self, path: str):
        """从 JSON 加载锚点库"""
        import json
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.anchor_library = data.get("content_libraries", {}).get("anchor_phrases", {})

    def convert(self, packet: Dict, node: Dict, pc: Character) -> ViewModelResult:
        """
        核心转换：裁决输出包 → ViewModelResult
        packet: Model 层产出的 ResolutionPacket
        node: module.json 中的场景节点
        pc: 当前角色
        """
        result = ViewModelResult()

        # 1. 叙事转换
        result.narrative = self._lookup_anchor(packet, node)

        # 2. 衍生状态标签
        result.derived_tags = self._derive_tags(packet)

        # 3. 特征触发检查
        result.triggered_features = self._check_triggers(packet, pc)

        # 4. 事件队列
        result.queued_events = self._build_event_queue(packet)

        # 5. 专注点可用动作
        result.available_focus_actions = self._available_focus_actions(packet, node, pc)

        # 6. 选择项
        result.choices = self._build_choices(packet, node)

        # 7. 状态变更
        result.status_changes = self._calc_status_changes(packet)

        return result

    def convert_combat(self, combat_packet: Dict, pc: Character) -> ViewModelResult:
        """战斗专用转换"""
        result = ViewModelResult()

        result.narrative = self._lookup_damage_anchor(combat_packet)
        result.derived_tags = self._derive_tags(combat_packet)
        result.triggered_features = self._check_triggers(combat_packet, pc)
        result.status_changes = {
            "hp_delta": -combat_packet.get("damage", 0),
            "location": combat_packet.get("location", "躯干"),
        }
        return result

    def scene_resolution_narrative(self, rewards: Dict, pc: Character) -> str:
        """场景结算叙事"""
        parts = []
        parts.append("╔══════════════════════════════════╗")
        parts.append("║       场景结算                   ║")
        if rewards.get("focus_restored", 0) > 0:
            parts.append(f"║  ○ 专注点: +{rewards['focus_restored']}                    ║")
        if rewards.get("marks_healed", 0) > 0:
            parts.append(f"║  印记: -{rewards['marks_healed']} (安全节点)              ║")
        if rewards.get("xp", 0) > 0:
            parts.append(f"║  XP: +{rewards['xp']}                       ║")
        parts.append("╚══════════════════════════════════╝")
        return "\n".join(parts)

    # === 私有方法 ===

    def _lookup_anchor(self, packet: Dict, node: Dict) -> str:
        """从锚点库查表"""
        anchors = node.get("layer_narrative", {}).get("anchor_phrases", {})

        if packet.get("is_crit_success"):
            key = anchors.get("crit_success")
            if key:
                return key
        if packet.get("success"):
            for key_name in ["success", "success_brute", "success_finesse"]:
                key = anchors.get(key_name)
                if key:
                    return key
            return "检定成功。"
        else:
            key = anchors.get("failure")
            if key:
                return key
            # 根据 margin 生成描述
            margin = abs(packet.get("margin", 0))
            if margin >= 8:
                return "彻底失败——差距之大令人沮丧。"
            elif margin >= 4:
                return "差了一大截——动作变形了。"
            return "差了一点——几乎是擦边而过。"

    def _lookup_damage_anchor(self, packet: Dict) -> str:
        """从锚点库查找伤害描述"""
        damage = packet.get("damage", 0)
        dtype = packet.get("type", "钝击")
        location = packet.get("location", "躯干")
        dr = packet.get("dr", 0)

        # 构建查表键
        if damage <= 0:
            return f"攻击打在护甲上，只擦出一声闷响。（DR {dr} 完全吸收）"

        if damage <= 2:
            tier = "轻伤"
        elif damage <= 5:
            tier = "中等"
        else:
            tier = "重伤"

        # 尝试从库中查找
        key_map = {
            ("钝击", "头"): "blunt_head",
            ("穿刺", "躯干"): "impaling_torso",
            ("切割", "躯干"): "cutting_torso",
            ("切割", "手臂"): "cutting_limb",
            ("切割", "腿"): "cutting_limb",
        }
        lib_key = key_map.get((dtype, location))
        if lib_key and lib_key in self.anchor_library:
            tier_key = {
                "轻伤": "1-3", "中等": "4-7", "重伤": "8+"
            }.get(tier, "4-7")
            phrase = self.anchor_library[lib_key].get(tier_key)
            if phrase:
                return phrase

        # 默认叙事
        return f"攻击命中{location}，造成 {damage} 点{dtype}伤害。"

    def _derive_tags(self, packet: Dict) -> List[Dict]:
        """从裁决包衍生状态标签"""
        tags = []
        damage = packet.get("damage", 0)
        location = packet.get("location", "")
        location_effects = packet.get("location_effects", {})

        if isinstance(location_effects, dict):
            for effect_name, modifier in location_effects.items():
                tags.append({"name": effect_name, "modifier": modifier, "duration": "scene"})
        elif isinstance(location_effects, list):
            for item in location_effects:
                if isinstance(item, str):
                    tags.append({"name": item, "modifier": -1, "duration": "scene"})
                elif isinstance(item, dict):
                    tags.append({"name": item.get("name", ""), "modifier": item.get("modifier", -1), "duration": "scene"})

        if damage >= 5 and "臂" in location:
            tags.append({"name": "武器把持-2", "modifier": -2, "duration": "scene"})
        if damage >= 5 and "腿" in location:
            tags.append({"name": "移动-2", "modifier": -2, "duration": "scene"})

        return tags

    def _check_triggers(self, packet: Dict, pc: Character) -> List[Dict]:
        """检查角色特征的触发条件"""
        triggered = []
        for f in pc.features:
            if f.used_this_scene >= f.per_scene_limit:
                continue
            # 简单触发匹配（基于 packet 中的关键词）
            if self._match_trigger(f.trigger_condition, packet):
                triggered.append({
                    "name": f.name,
                    "effect": f.effect,
                    "cost": f.cost,
                })
        return triggered

    def _match_trigger(self, condition: str, packet: Dict) -> bool:
        """检查触发条件是否匹配（简化版）"""
        cond_lower = condition.lower()
        if "追踪" in cond_lower or "tracking" in cond_lower:
            return packet.get("action_type") == "tracking"
        if "受伤" in cond_lower or "damage" in cond_lower:
            return packet.get("damage", 0) > 0
        if packet.get("is_crit_success"):
            return "大成功" in cond_lower or "crit" in cond_lower
        return False

    def _build_event_queue(self, packet: Dict) -> List[Dict]:
        """构造事件队列"""
        queue = []
        if not packet.get("success"):
            queue.append({
                "trigger": "next_check",
                "effect": {"tag_add": {"name": "挫败感", "modifier": -1, "duration": "1 check"}},
            })
        if packet.get("is_fumble"):
            queue.append({
                "trigger": "immediate",
                "effect": {"self_damage": max(1, abs(packet.get("margin", 1)) // 3)},
            })
        return queue

    def _available_focus_actions(self, packet: Dict, node: Dict, pc: Character) -> List[str]:
        """计算当前可用的专注点动作"""
        actions = []
        if pc.focus_points >= 1:
            actions.append("声明细节：向场景添加一个情境标签")
            for f in pc.features:
                if f.used_this_scene < f.per_scene_limit:
                    actions.append(f"特征触发：{f.name} ({f.effect})")
        return actions

    def _build_choices(self, packet: Dict, node: Dict) -> List[Dict]:
        """构建选择项（给 View 层渲染）"""
        choices = []
        next_nodes = node.get("next_nodes", [])
        for nn in next_nodes:
            if isinstance(nn, str):
                choices.append({"label": f"前往 {nn}", "action": "goto_node", "target": nn})
            elif isinstance(nn, dict):
                choices.append(nn)
        return choices

    def _calc_status_changes(self, packet: Dict) -> Dict:
        """计算状态变更"""
        changes = {}
        if packet.get("damage", 0) > 0:
            changes["hp_delta"] = -packet["damage"]
        if packet.get("cost_fp", 0) > 0:
            changes["fp_delta"] = -packet["cost_fp"]
        return changes
