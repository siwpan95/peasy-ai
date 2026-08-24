# -*- coding: utf-8 -*-
"""
迷失之镜 — 核心引擎 (Model 层)
MVVM 架构：Model（GURPS 物理）→ ViewModel（叙事转换）→ View（终端渲染）

v2.0: 数据驱动场景引擎 + 完整 MVVM 分离
"""
import json
import os
import random
import sys

from core.character import Character, CharacterFeature, Skill, Equipment
from core.enemy import Enemy
from core.scene_engine import SceneEngine
from core.environment_system import EnvironmentSystem
from core.viewmodel import ViewModel, ViewModelResult
from core.combat_engine import CombatEngine
from services.item_system import ItemSystem
from services.scene_resolver import SceneResolver
from services.xp_system import XPSystem
from services.save_manager import SaveManager
from view.terminal_renderer import TerminalRenderer


class MirrorOfLost:
    """
    迷失之镜核心引擎 v2.0
    Model 层：GURPS 物理裁决 + 状态管理
    """

    def __init__(self, system_file: str, module_file: str):
        # 加载配置
        with open(system_file, 'r', encoding='utf-8') as f:
            self.system = json.load(f)
        with open(module_file, 'r', encoding='utf-8') as f:
            self.module = json.load(f)

        # 子系统
        self.pc: Character = None
        self.env = EnvironmentSystem()
        self.vm = ViewModel()
        self.combat = CombatEngine()
        self.items = ItemSystem()
        self.resolver = SceneResolver()
        self.xp_sys = XPSystem()
        self.saver = SaveManager()
        self.renderer = TerminalRenderer()

        # 场景引擎（延迟初始化）
        self.engine: SceneEngine = None

        # 加载锚点库
        self.vm.load_anchors = self._load_anchors

        # 初始化环境
        self._init_environment()

    def _load_anchors(self, path: str = None):
        """从 system.json 加载锚点库"""
        self.vm.anchor_library = self.system.get("content_libraries", {}).get("anchor_phrases", {})

    def _init_environment(self):
        """初始化环境系统"""
        tags = self.module.get("global_context_tags", [])
        self.env.load_tags(tags)

    def set_character(self, pc: Character):
        """设置玩家角色"""
        self.pc = pc
        # 创建场景引擎
        self.engine = SceneEngine(self.module, self.pc, self.vm, self.env)
        # 加载锚点
        self._load_anchors()

    def create_default_character(self) -> Character:
        """创建默认角色"""
        pc = Character(
            character_id="default_investigator",
            name="调查员",
            st=10, dx=10, iq=12, ht=10,
            hp=10, hp_max=10, fp=10, fp_max=10,
            will=11, per=12,
            skills=[
                Skill("调查", 13, "Avg", "IQ", 4),
                Skill("潜行", 11, "Avg", "DX", 2),
                Skill("近战", 11, "Avg", "DX", 2),
                Skill("急救", 12, "Easy", "IQ", 1),
            ],
            advantages=["警觉"],
            disadvantages=["好奇心"],
            features=[
                CharacterFeature("猎手直觉", "追踪/瞄准时有可见痕迹", 1,
                                 "请求目标听觉/视觉 -2", 1),
            ],
            anchors=["怀表", "旧伤疤"],
            focus_points=3, focus_max=3, luck_points=2, luck_max=2,
        )
        return pc

    # === 物理层 (Model) ===

    def roll_3d6(self) -> int:
        return sum(random.randint(1, 6) for _ in range(3))

    def physical_resolve(self, skill_level: int, modifier: int = 0) -> dict:
        """执行物理裁决，返回 ResolutionPacket"""
        roll = self.roll_3d6()
        target = skill_level + modifier
        success = roll <= target
        return {
            "roll": roll,
            "target": target,
            "success": success,
            "margin": target - roll,
            "is_crit_success": roll <= 4,
            "is_fumble": roll >= 17,
        }

    # === 战斗 ===

    def start_combat(self, enemy_data: dict) -> CombatEngine:
        """开始战斗"""
        enemy = Enemy.from_dict(enemy_data)
        self.combat.init_combat(self.pc, [enemy])
        return self.combat

    def combat_player_attack(self, skill_level: int, is_reverse: bool = False) -> dict:
        """玩家攻击"""
        if not self.combat.state:
            return {"success": False, "error": "战斗未开始"}
        # 找到敌人
        enemy = None
        for p in self.combat.state.participants:
            if p["name"] != "PC":
                enemy = p["entity"]
                break
        if not enemy:
            return {"success": False, "error": "无敌人"}
        if not self.combat._entity_alive(enemy):
            return {"success": False, "error": "敌人已死亡"}

        packet = self.combat.attack_resolve(self.pc, enemy, skill_level, is_reverse)

        if packet["success"]:
            # 应用伤害
            is_mook = getattr(enemy, 'enemy_type', '') == 'mook'
            result = self.combat.apply_damage(enemy, packet, is_mook)

            # ViewModel 转换战斗结果
            vm_result = self.vm.convert_combat(packet, self.pc)
            # 应用角色伤害
            for tag in vm_result.derived_tags:
                self.pc.add_tag(tag["name"], tag.get("modifier", 0))

            packet["vm_result"] = vm_result
            packet["mook_result"] = result

        return packet

    def combat_enemy_attack(self) -> dict:
        """敌人攻击 PC"""
        if not self.combat.state:
            return {"success": False}
        enemy = None
        for p in self.combat.state.participants:
            if p["name"] != "PC":
                enemy = p["entity"]
                break
        if not enemy or not self.combat._entity_alive(enemy):
            return {"success": False}

        packet = self.combat.attack_resolve(enemy, self.pc,
                                            getattr(enemy, 'attack_skill', 12))
        if packet["success"]:
            self.combat.apply_damage(self.pc, packet, False)
        return packet

    def try_active_defense(self, packet: dict) -> dict:
        """尝试主动防御"""
        defense = self.combat.active_defense(self.pc, packet)
        if defense["result"] == "dodged":
            # 撤销伤害
            packet["damage"] = 0
            packet["penetrated"] = 0
        return defense

    # === 场景引擎 ===

    def run_node(self, node_id: str, choice: str = None) -> ViewModelResult:
        """运行场景节点"""
        if not self.engine:
            vm_result = ViewModelResult()
            vm_result.narrative = "错误：场景引擎未初始化。请先设置角色。"
            return vm_result
        return self.engine.run_node(node_id, choice)

    def get_available_nodes(self) -> list:
        """获取可用节点列表"""
        if not self.engine:
            return []
        return self.engine.get_available_nodes()

    def get_progress(self) -> dict:
        """获取游戏进度"""
        if not self.engine:
            return {"total_nodes": 0, "completed_nodes": 0, "current_act": "act_1", "flags": {}}
        return self.engine.get_progress_summary()

    # === 存档 ===

    def save_game(self, save_name: str = None) -> str:
        """保存游戏"""
        name = save_name or self.module.get("meta", {}).get("module_id", "game")
        progress = self.get_progress()
        progress["completed_nodes_list"] = list(self.engine.completed_nodes) if self.engine else []
        progress["choices_log"] = self.engine.choices_log if self.engine else []
        return self.saver.save(name, self.pc, progress)

    def load_game(self, save_path: str) -> bool:
        """加载存档"""
        save_data = self.saver.load(save_path)
        if not save_data:
            return False

        # 恢复角色状态
        char_state = save_data.get("character_state", {})
        self.pc.restore_snapshot(char_state)

        # 恢复游戏进度
        progress = save_data.get("game_progress", {})
        if self.engine:
            self.engine.completed_nodes = set(progress.get("completed_nodes_list", []))
            self.engine.flags = progress.get("flags", {})
            self.engine.choices_log = progress.get("choices_log", [])
        return True

    # === 结算 ===

    def resolve_current_scene(self, is_safe: bool = False) -> dict:
        """当前场景结算"""
        if not self.engine or not self.engine.current_node:
            return {}
        return self.engine.resolve_scene(is_safe)

    def get_xp_reward(self) -> int:
        """计算 XP 奖励"""
        if not self.engine:
            return 0
        completed = len(self.engine.completed_nodes)
        flags = len(self.engine.flags)
        base = self.module.get("meta", {}).get("base_xp", 3)
        xp = self.xp_sys.calculate_xp(completed, flags, self.pc.psychic_marks, base)
        self.xp_sys.apply_xp(self.pc, xp)
        return xp

    # === 状态检查 ===

    def check_death(self) -> bool:
        """检查死亡"""
        return self.pc.hp <= 0

    def check_obsession(self) -> bool:
        """检查执念触发"""
        return self.pc.has_obsession

    def is_game_over(self) -> bool:
        """检查游戏是否结束"""
        if self.check_death():
            return True
        if self.engine and self.engine.is_act_complete("act_3"):
            return True
        return False

    @property
    def xp(self):
        """XP 系统快捷访问"""
        return self.xp_sys
