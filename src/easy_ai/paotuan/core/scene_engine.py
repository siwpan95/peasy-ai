# -*- coding: utf-8 -*-
"""
迷失之镜 — 数据驱动场景引擎 (Model 层 · 阶段 1)
读取 module.json nodes[] → 解析 scene_type → 驱动检定 → 调用 ViewModel → 状态变更
"""
import random
import json
import os
import re
from typing import Dict, List, Optional, Tuple, Any
from core.character import Character
from core.environment_system import EnvironmentSystem
from core.viewmodel import ViewModel, ViewModelResult
from core.combat_engine import CombatEngine
from core.enemy import Enemy
from services.scene_resolver import SceneResolver


def _parse_int(value, default=0):
    """从 JSON 值中提取整数，兼容 '+2（锤子/撬棍）' 等含注释的字符串"""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        m = re.match(r'([+-]?\d+)', value.strip())
        if m:
            return int(m.group(1))
    return default


class SceneEngine:
    """
    数据驱动场景引擎
    核心原则：模组 = JSON 数据包，引擎解释 JSON 就能跑任何模组
    """

    def __init__(self, module_data: Dict, pc: Character, view_model: ViewModel,
                 env_system: EnvironmentSystem):
        self.module = module_data
        self.pc = pc
        self.vm = view_model
        self.env = env_system
        self.combat = CombatEngine()
        self.resolver = SceneResolver()

        # 追踪上一次掷骰（给 View 层读取）
        self._last_packet: Optional[Dict] = None

        # 游戏进度
        self.completed_nodes: set = set()
        self.flags: Dict[str, Any] = {}
        self.choices_log: List[str] = []
        self.current_node: Optional[Dict] = None

        # 构建节点索引
        self._node_index: Dict[str, Dict] = {}
        self._build_node_index()

    def _build_node_index(self):
        """构建 node_id → node 的快速查找索引"""
        for act_key in ["act_1", "act_2", "act_3"]:
            act = self.module.get(act_key, {})
            for node in act.get("nodes", []):
                nid = node.get("node_id", "")
                if nid:
                    # 补充 scene_type（如果没有的话）
                    if "scene_type" not in node:
                        node["scene_type"] = self._infer_scene_type(node)
                    # 补充默认字段
                    node.setdefault("prerequisite_nodes", [])
                    node.setdefault("next_nodes", [])
                    node.setdefault("unlocks_flags", [])
                    self._node_index[nid] = node

    def _infer_scene_type(self, node: Dict) -> str:
        """从节点内容推断场景类型"""
        physics = node.get("layer_physics", {})
        if physics.get("enemy_type"):
            return "combat"
        if physics.get("skill_checks"):
            for c in physics["skill_checks"]:
                if "急救" in c.get("skill", "") or "诊断" in c.get("skill", ""):
                    return "investigation"
        skill = physics.get("skill_check", "")
        if "感知" in skill or "Perception" in skill:
            return "perception"
        if "力量" in skill or "ST" in skill:
            return "feat"
        return "explore"

    # === 核心：运行节点 ===

    def get_available_nodes(self) -> List[Dict]:
        """获取当前可用的节点列表"""
        available = []
        for nid, node in self._node_index.items():
            if nid in self.completed_nodes:
                continue
            if self._can_access(node):
                available.append(node)
        return available

    def _can_access(self, node: Dict) -> bool:
        """检查节点是否可访问"""
        prerequisites = node.get("prerequisite_nodes", [])
        for prereq in prerequisites:
            if prereq not in self.completed_nodes:
                return False

        # 检查 flag 条件
        required_flags = node.get("required_flags", [])
        for flag in required_flags:
            if flag not in self.flags:
                return False

        return True

    def run_node(self, node_id: str, player_choice: str = None) -> ViewModelResult:
        """运行指定节点，返回 ViewModelResult"""
        node = self._node_index.get(node_id)
        if not node:
            vm_result = ViewModelResult()
            vm_result.narrative = f"错误：找不到节点 {node_id}"
            return vm_result

        self.current_node = node
        scene_type = node.get("scene_type", "explore")

        # 进入场景 → 更新环境
        self.env.on_scene_enter(node)

        # 根据场景类型分发
        if scene_type == "combat":
            return self._handle_combat_node(node)

        # 通用检定节点
        return self._handle_check_node(node, player_choice)

    def _handle_check_node(self, node: Dict, player_choice: str = None) -> ViewModelResult:
        """处理通用检定节点（支持嵌套检定）"""
        physics = node.get("layer_physics", {})

        # 检查是否有 checks 数组（嵌套检定模式）
        checks = physics.get("checks", [])

        if checks:
            return self._handle_nested_checks(checks, node)

        # 单检定模式
        skill_check = physics.get("skill_check", "")
        modifier = _parse_int(physics.get("modifier", 0))
        tool_bonus = _parse_int(physics.get("tool_bonus", 0))

        # 环境修正
        env_mod = self.env.get_active_modifiers()
        modifier += env_mod

        # 查找技能等级
        skill_level = 10  # 默认
        if "感知" in skill_check or "Per" in skill_check:
            skill_level = self.pc.per
        elif "力量" in skill_check or "ST" in skill_check:
            skill_level = self.pc.st
        elif "意志" in skill_check or "Will" in skill_check:
            skill_level = self.pc.will
        elif "体质" in skill_check or "HT" in skill_check:
            skill_level = self.pc.ht
        elif "敏捷" in skill_check or "DX" in skill_check:
            skill_level = self.pc.dx
        elif "智力" in skill_check or "IQ" in skill_check:
            skill_level = self.pc.iq
        else:
            # 尝试匹配技能名
            sl = self.pc.get_skill_level(skill_check)
            if sl is not None:
                skill_level = sl

        # 角色标签修正
        tag_mod = self.pc.calc_tag_modifier()
        modifier += tag_mod

        target = skill_level + modifier + tool_bonus
        roll = sum(random.randint(1, 6) for _ in range(3))

        packet = {
            "roll": roll,
            "target": target,
            "success": roll <= target,
            "margin": target - roll,
            "is_crit_success": roll <= 4,
            "is_fumble": roll >= 17,
            "action_type": node.get("scene_type", "check"),
            "skill_used": skill_check,
            "modifiers": {"base": modifier, "env": env_mod, "tag": tag_mod, "tool": tool_bonus},
        }

        # 记录最后一次掷骰（给 View 层读取）
        self._last_packet = packet

        # 失败时可能触发精神印记
        psychic = node.get("psychic_marks")
        if psychic and not packet["success"]:
            self.pc.add_psychic_mark(_parse_int(psychic.get("failure_cost", 1)))

        # ViewModel 转换
        vm_result = self.vm.convert(packet, node, self.pc)

        # 应用状态变更
        self._apply_status_changes(vm_result.status_changes)

        # 应用衍生标签
        for tag in vm_result.derived_tags:
            self.pc.add_tag(tag["name"], tag.get("modifier", 0), tag.get("duration", "scene"))

        # 应用环境更新
        self.env.resolve_environment_update(vm_result.environment_update)

        # 标记完成
        self.completed_nodes.add(node["node_id"])
        self.choices_log.append(f"节点 {node['node_id']}: success={packet['success']}")

        return vm_result

    def _handle_nested_checks(self, checks: List[Dict], node: Dict) -> ViewModelResult:
        """处理嵌套检定序列"""
        all_results = []
        final_success = True

        for check in checks:
            check_type = check.get("type", "automatic")

            if check_type == "choice":
                # 需要玩家选择（由 View 层处理）
                vm_result = ViewModelResult()
                vm_result.narrative = check.get("prompt", "")
                vm_result.choices = []
                for opt in check.get("options", []):
                    vm_result.choices.append({
                        "label": opt["label"],
                        "action": "check_choice",
                        "check_data": {
                            "skill": opt.get("skill", "ST"),
                            "dc": opt.get("dc", 10),
                            "on_success": opt.get("on_success", {}),
                            "on_failure": opt.get("on_failure", {}),
                        },
                    })
                return vm_result

            else:
                # 自动检定
                skill_name = check.get("skill", "ST")
                dc = _parse_int(check.get("dc", 10))
                skill_map = {"strength": self.pc.st, "agility": self.pc.dx,
                             "dexterity": self.pc.dx, "intelligence": self.pc.iq,
                             "health": self.pc.ht, "perception": self.pc.per}
                skill_level = skill_map.get(skill_name, self.pc.get_skill_level(skill_name) or 10)

                target = skill_level
                roll = sum(random.randint(1, 6) for _ in range(3))
                success = roll <= dc

                result = {"check_id": check.get("id", ""), "success": success,
                          "roll": roll, "dc": dc}
                all_results.append(result)

                if success:
                    on_success = check.get("on_success", {})
                    for flag in on_success.get("flag_set", []):
                        self.flags[flag] = True
                    # 如果 on_success 有 next，继续；否则结束
                    if not on_success.get("next"):
                        break
                else:
                    on_failure = check.get("on_failure", {})
                    damage = _parse_int(on_failure.get("damage", 0))
                    if damage:
                        self.pc.hp -= damage
                    final_success = False
                    break

        # 构建最终结果
        packet = {
            "success": final_success,
            "nested_results": all_results,
            "action_type": "nested_check",
        }

        vm_result = self.vm.convert(packet, node, self.pc)
        self.completed_nodes.add(node["node_id"])
        return vm_result

    def _handle_combat_node(self, node: Dict) -> ViewModelResult:
        """处理战斗节点"""
        physics = node.get("layer_physics", {})

        # 从 JSON 构建敌人
        enemy_type = physics.get("enemy_type", "mook")
        stats = physics.get("unit_stats", {})

        enemy_name = node.get("title", node.get("trigger", "未知敌人"))
        enemy = Enemy(
            name=enemy_name,
            enemy_type="wildcard" if "wildcard" in enemy_type.lower() else "mook",
            hp=stats.get("hp", 10),
            hp_max=stats.get("hp", 10),
            attack_skill=stats.get("attack_skill", 12),
            damage=stats.get("damage", "1d6 cut"),
            dodge=stats.get("dodge", 8),
        )

        # 特殊机制
        special = physics.get("special_mechanic", {})
        if special:
            enemy.special_abilities.append(special)

        vm_result = ViewModelResult()
        vm_result.narrative = node.get("layer_narrative", {}).get("anchor_phrases", {}).get("success", "战斗开始！")
        vm_result.choices = [{
            "label": "⚔️ 进入战斗",
            "action": "start_combat",
            "enemy": enemy.to_dict(),
            "node_id": node["node_id"],
        }]

        self.completed_nodes.add(node["node_id"])
        return vm_result

    # === 状态管理 ===

    def _apply_status_changes(self, changes: Dict):
        """应用 ViewModel 产出的状态变更"""
        if changes.get("hp_delta"):
            self.pc.hp = max(0, self.pc.hp + changes["hp_delta"])
        if changes.get("fp_delta"):
            self.pc.fp = max(0, self.pc.fp + changes["fp_delta"])

    def resolve_scene(self, is_safe: bool = False) -> Dict:
        """当前节点完成后的场景结算"""
        if not self.current_node:
            return {}
        node_result = {"is_safe_node": is_safe, "is_major_challenge": True}
        return self.resolver.resolve(node_result, self.pc, self.current_node)

    # === 进度追踪 ===

    def is_act_complete(self, act_key: str) -> bool:
        """检查某幕是否完成"""
        act = self.module.get(act_key, {})
        nodes = act.get("nodes", [])
        if not nodes:
            return False
        return all(n["node_id"] in self.completed_nodes for n in nodes)

    def get_progress_summary(self) -> Dict:
        """获取进度摘要"""
        total = len(self._node_index)
        done = len(self.completed_nodes)
        current_act = "act_1"
        if self.is_act_complete("act_1"):
            current_act = "act_2"
        if self.is_act_complete("act_2"):
            current_act = "act_3"

        return {
            "total_nodes": total,
            "completed_nodes": done,
            "current_act": current_act,
            "flags": dict(self.flags),
        }
