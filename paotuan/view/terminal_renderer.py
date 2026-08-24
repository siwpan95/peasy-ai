# -*- coding: utf-8 -*-
"""
迷失之镜 — 终端渲染器 (View 层 · 阶段 V)
所有终端输出收拢到一个模块。只消费 ViewModelResult，不直接读 Model。
"""
from typing import List, Dict, Optional
from core.character import Character
from .character_sheet import CharacterSheet


class TerminalRenderer:
    """终端渲染器 —— View 层唯一实现"""

    def __init__(self):
        self.width = 52

    # === 开场 / 结尾 ===

    def render_intro(self, module_name: str):
        """开场画面"""
        lines = [
            "",
            "=" * self.width,
            "     ███╗   ███╗██╗██████╗ ",
            "     ████╗ ████║██║██╔══██╗",
            "     ██╔████╔██║██║██████╔╝",
            "     ██║╚██╔╝██║██║██╔══██╗",
            "     ██║ ╚═╝ ██║██║██║  ██║",
            "     ╚═╝     ╚═╝╚═╝╚═╝  ╚═╝",
            "     迷失之镜 · 三层架构 TRPG 引擎",
            "     GURPS 物理 | Fate 叙事 | Savage 节奏",
            "=" * self.width,
            f"     🎭 正在跑团: {module_name}",
            "=" * self.width,
        ]
        print("\n".join(lines))

    def render_outro(self):
        """结束画面"""
        print("\n" + "=" * self.width)
        print("     感谢游玩《迷失之镜》")
        print("     GURPS is © Steve Jackson Games")
        print("=" * self.width)

    # === 状态栏 ===

    def render_status_bar(self, pc: Character, env=None):
        """渲染状态栏"""
        marks = pc.psychic_marks
        hp = pc.hp
        hp_max = pc.hp_max
        fp = pc.focus_points
        lp = pc.luck_points

        hp_ratio = hp / max(hp_max, 1)
        if hp_ratio > 0.6:
            hp_bar = "🟢"
        elif hp_ratio > 0.3:
            hp_bar = "🟡"
        else:
            hp_bar = "🔴"

        print(f"\n{'=' * self.width}")
        print(f"  {hp_bar} HP: {hp}/{hp_max}  |  FP: {pc.fp}/{pc.fp_max}")
        print(f"  ✨ 专注点: {fp}/{pc.focus_max}  |  🍀 幸运点: {lp}/{pc.luck_max}")
        print(f"  💀 精神印记: {marks}" + (" ⚠️ 临界！" if marks >= 3 else ""))
        if env:
            tags = env.get_tag_names()
            if tags:
                print(f"  🌍 环境: {', '.join(tags[:3])}")
        print(f"{'=' * self.width}")

    # === 场景标题 ===

    def render_scene_header(self, node: Dict):
        """场景标题 + 触发描述"""
        scene_id = node.get("node_id", "?")
        trigger = node.get("trigger", "")
        scene_type = node.get("scene_type", "explore")
        type_emoji = {"combat": "⚔️", "perception": "🔍", "investigation": "🔎",
                      "explore": "🚶", "feat": "💪", "social": "💬"}.get(scene_type, "📜")

        print(f"\n{'─' * 36}")
        print(f"  {type_emoji} 场景 {scene_id} [{scene_type}]")
        if trigger:
            print(f"  {trigger}")
        print(f"{'─' * 36}")

    # === 选择菜单 ===

    def render_choice_prompt(self, choices: List[Dict]):
        """渲染选择菜单"""
        for i, choice in enumerate(choices, 1):
            label = choice.get("label", f"选项 {i}")
            desc = choice.get("description", "")
            available = choice.get("available", True)
            marker = "  " if available else "🔒"
            print(f"  {marker}{i}. {label}")
            if desc:
                print(f"     {desc}")

    def render_scene_menu(self, available_nodes: List[Dict], completed_nodes: set):
        """渲染场景选择菜单"""
        print("\n📋 可选行动：")
        for i, node in enumerate(available_nodes, 1):
            scene_type = node.get("scene_type", "explore")
            type_icon = {"combat": "⚔️", "perception": "🔍", "explore": "🚶",
                         "investigation": "🔎", "feat": "💪"}.get(scene_type, "📜")
            trigger = node.get("trigger", node["node_id"])
            status = " ✅" if node["node_id"] in completed_nodes else ""
            print(f"  {i}. {type_icon} {trigger[:40]}{status}")

    # === 裁决结果 ===

    def render_resolution(self, vm_result):
        """渲染裁决结果叙事"""
        print(f"\n📖 {vm_result.narrative}")

        # 显示掷骰信息（如果 VM 包含）
        if hasattr(vm_result, 'roll_info') and vm_result.roll_info:
            ri = vm_result.roll_info
            print(f"   🎲 掷出 {ri['roll']}（目标 {ri['target']}）— {'✓ 成功' if ri['success'] else '✗ 失败'}")

        # 衍生标签
        if vm_result.derived_tags:
            for tag in vm_result.derived_tags:
                print(f"   🏷️  {tag['name']} ({int(tag.get('modifier', 0)):+d})")

        # 触发特征
        if vm_result.triggered_features:
            for feat in vm_result.triggered_features:
                print(f"   ⚡ 触发特征：【{feat['name']}】— {feat.get('effect', '')}")

        # 专注点可用动作
        if vm_result.available_focus_actions:
            print("\n   💡 可用专注点动作：")
            for action in vm_result.available_focus_actions[:3]:
                print(f"      ○ {action}")

    # === 战斗画面 ===

    def render_combat_round(self, round_state: Dict):
        """战斗回合画面"""
        round_num = round_state.get("round_num", 1)
        print(f"\n--- 第 {round_num} 回合 ---")

    def render_combat_result(self, packet: Dict, defense: Dict = None):
        """战斗结果"""
        if packet.get("success"):
            if defense and defense.get("result") == "dodged":
                print(f"  ↪️ {defense.get('narrative', '闪避成功！')}")
            else:
                location = packet.get("location", "?")
                damage = packet.get("damage", 0)
                dtype = packet.get("type", "")
                print(f"  💥 命中{location}！造成 {damage} 点{dtype}伤害。")
        elif packet.get("is_fumble"):
            print(f"  💀 大失败！（掷出 {packet.get('roll', '?')}）")
        else:
            print(f"  ✗ 攻击失误！（掷出 {packet.get('roll', '?')}，目标 {packet.get('target', '?')}）")

    # === 角色卡 ===

    def render_character_sheet(self, pc: Character):
        """渲染角色卡"""
        print(CharacterSheet.render(pc))

    # === 场景结算 ===

    def render_settlement(self, rewards: Dict):
        """场景结算面板"""
        print(f"\n📊 场景结算:")
        if rewards.get("focus_restored", 0) > 0:
            print(f"   ✨ 专注点 +{rewards['focus_restored']}")
        if rewards.get("marks_healed", 0) > 0:
            print(f"   🩹 印记 -{rewards['marks_healed']}")
        if rewards.get("xp", 0) > 0:
            print(f"   ⭐ XP +{rewards['xp']}")
        if rewards.get("narrative"):
            print(f"   💀 {rewards['narrative']}")

    # === 系统信息 ===

    def render_module_select(self, modules: List[Dict]):
        """模组选择列表"""
        print(f"\n  📦 可用模组 ({len(modules)} 个):")
        print("  " + "─" * 48)
        for i, mod in enumerate(modules, 1):
            tag = f" [{mod.get('playstyle', '')}]" if mod.get('playstyle') else ""
            print(f"  {i}. {mod['title']}  v{mod.get('version','?')}  by {mod.get('author','?')}{tag}")
            if mod.get('synopsis'):
                print(f"     {mod['synopsis'][:50]}")
            print(f"     {mod.get('duration','?')}  |  {mod.get('players','?')}")
            print()

    def render_character_select(self, characters: List[Character]):
        """角色选择列表"""
        print(f"\n  👤 可用角色 ({len(characters)} 个):")
        print("  " + "─" * 48)
        for i, char in enumerate(characters, 1):
            print(f"  {i}. {char.name}  ST{char.st}/DX{char.dx}/IQ{char.iq}/HT{char.ht}")
            if char.advantages:
                print(f"    优势: {', '.join(char.advantages[:2])}")
            print()

    def render_save_confirm(self, save_path: str):
        """存档确认"""
        print(f"\n💾 游戏已保存: {save_path}")

    def render_load_list(self, saves: List[Dict]):
        """存档列表"""
        if not saves:
            print("\n  📂 没有找到存档。")
            return
        print(f"\n  💾 存档列表 ({len(saves)} 个):")
        print("  " + "─" * 48)
        for i, save in enumerate(saves, 1):
            print(f"  {i}. {save['save_name']}  [{save['timestamp']}]")
            print(f"     角色: {save['character_name']}")

    def render_help(self):
        """帮助信息"""
        print("""
╔══════════════════════════════════════╗
║         迷失之镜 — 帮助             ║
╠══════════════════════════════════════╣
║  🎯 专注点 (○)：花 1 点声明细节     ║
║                 或触发角色特征       ║
║  🍀 幸运点 (♦)：花 1 点重掷骰子     ║
║  💀 精神印记：3 点触发执念特质      ║
║  C 键：查看角色卡                   ║
║  S 键：保存游戏                     ║
║  ✨ 每完成场景回复 1 专注点          ║
║  专注点改情境 | 幸运点改骰子         ║
╚══════════════════════════════════════╝""")

    def render_error(self, msg: str):
        """错误信息"""
        print(f"\n⚠️  {msg}")

    def render_info(self, msg: str):
        """普通信息"""
        print(f"\n   {msg}")

    def render_divider(self):
        """分隔线"""
        print(f"\n{'─' * self.width}")

    def print(self, text: str):
        """通用输出"""
        print(text)
