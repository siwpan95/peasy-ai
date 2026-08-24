# -*- coding: utf-8 -*-
"""
迷失之镜 — 模组管理器与启动入口 v2.0
MVVM 三层架构：Model（GURPS）→ ViewModel（叙事）→ View（终端渲染）
Scenengine 驱动的动态菜单 + 角色选择 + 存档 + C/S 快捷键
"""
import json
import os
import random
import sys

from view.terminal_renderer import TerminalRenderer

# Windows GBK 终端兼容
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODULES_DIR = os.path.join(BASE_DIR, "modules")
SYSTEM_FILE = os.path.join(BASE_DIR, "config", "system.json")
CHARS_DIR = os.path.join(BASE_DIR, "characters")


# ==================== 模组管理器 ====================

class ModuleManager:
    """模组池管理器"""

    def __init__(self, modules_dir=MODULES_DIR):
        self.modules_dir = modules_dir
        self._modules = []
        os.makedirs(self.modules_dir, exist_ok=True)

    @property
    def modules(self):
        if not self._modules:
            self.scan()
        return self._modules

    def scan(self):
        self._modules = []
        if not os.path.isdir(self.modules_dir):
            return self._modules
        for entry in sorted(os.listdir(self.modules_dir)):
            mod_dir = os.path.join(self.modules_dir, entry)
            if not os.path.isdir(mod_dir):
                continue
            mod_file = os.path.join(mod_dir, "module.json")
            if not os.path.isfile(mod_file):
                continue
            try:
                with open(mod_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                meta = data.get("meta", {})
                if not meta.get("module_title"):
                    continue
                self._modules.append({
                    "id": meta.get("module_id", entry),
                    "dir": entry, "path": mod_file,
                    "title": meta["module_title"],
                    "author": meta.get("author", "未知"),
                    "version": meta.get("version", "?"),
                    "playstyle": meta.get("playstyle", ""),
                    "duration": meta.get("estimated_duration", ""),
                    "players": meta.get("player_count", ""),
                    "synopsis": meta.get("synopsis", ""),
                })
            except Exception:
                continue
        return self._modules

    def reload(self):
        self._modules = []
        self.scan()

    def create_template(self):
        """生成新模组模板"""
        print("\n  📝 创建新模组模板")
        title = input("  模组标题: ").strip()
        if not title:
            return
        import re
        safe = re.sub(r'[^a-z0-9\u4e00-\u9fff]', '_', title.lower())
        safe = re.sub(r'_+', '_', safe).strip('_') or "new_module"
        author = input("  作者: ").strip() or "未知"
        playstyle = input("  风格: ").strip() or "自定义"
        duration = input("  时长: ").strip() or "?"
        players = input("  人数: ").strip() or "?"
        synopsis = input("  简介: ").strip() or "新的冒险……"

        mod_dir = os.path.join(self.modules_dir, safe)
        if os.path.exists(mod_dir):
            print(f"  ⚠️ 目录已存在: {safe}")
            return
        os.makedirs(mod_dir, exist_ok=True)

        template = {
            "meta": {
                "module_id": safe, "module_title": title, "version": "0.1",
                "author": author, "playstyle": playstyle,
                "estimated_duration": duration, "player_count": players,
                "synopsis": synopsis, "base_xp": 3,
            },
            "global_context_tags": [],
            "act_1": {
                "scene_id": "act1", "title": "第一幕", "description": "",
                "nodes": [{
                    "node_id": "1.1", "scene_type": "explore", "trigger": "触发条件",
                    "prerequisite_nodes": [], "next_nodes": [],
                    "layer_physics": {"skill_check": "感知", "modifier": 0},
                    "layer_narrative": {"anchor_phrases": {
                        "success": "成功……", "failure": "失败……", "crit_success": "大成功！"
                    }}
                }]
            },
            "act_2": {"scene_id": "act2", "title": "第二幕", "description": "", "nodes": []},
            "act_3": {"scene_id": "act3", "title": "第三幕", "description": "", "nodes": []},
            "gm_cheatsheet": {"quick_ref_table": []},
        }
        with open(os.path.join(mod_dir, "module.json"), "w", encoding="utf-8") as f:
            json.dump(template, f, ensure_ascii=False, indent=2)
        print(f"  ✅ 已创建: modules/{safe}/module.json")


# ==================== 启动器 ====================

class MirrorLauncher:
    """启动器 v2.0 — 动态菜单 + 数据驱动"""

    def __init__(self):
        self.manager = ModuleManager()
        self.renderer = TerminalRenderer()

    def show_splash(self):
        self.renderer.render_intro("模组大厅")

    def select_module(self):
        """选择模组"""
        modules = self.manager.modules
        if not modules:
            print("\n  ⚠️ 没有找到模组。运行 --create-template 创建新模组。")
            return None

        self.renderer.render_module_select(modules)
        print("  输入编号选择，'t' 创建模板，'q' 退出。")

        while True:
            choice = input("\n  请选择: ").strip().lower()
            if choice == "q":
                return None
            if choice == "r":
                self.manager.reload()
                modules = self.manager.modules
                return self.select_module()
            if choice == "t":
                self.manager.create_template()
                self.manager.reload()
                modules = self.manager.modules
                return self.select_module()
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(modules):
                    return modules[idx]
            except ValueError:
                pass
            print("  ⚠️ 无效输入。")

    def select_character(self) -> str:
        """选择或创建角色"""
        chars = []
        if os.path.isdir(CHARS_DIR):
            for f in sorted(os.listdir(CHARS_DIR)):
                if f.endswith(".json"):
                    try:
                        with open(os.path.join(CHARS_DIR, f), "r", encoding="utf-8") as fp:
                            data = json.load(fp)
                        chars.append({
                            "file": os.path.join(CHARS_DIR, f),
                            "name": data.get("name", f),
                            "st": data.get("attributes", {}).get("ST", 10),
                            "dx": data.get("attributes", {}).get("DX", 10),
                            "iq": data.get("attributes", {}).get("IQ", 10),
                            "ht": data.get("attributes", {}).get("HT", 10),
                            "advantages": data.get("advantages", []),
                        })
                    except Exception:
                        continue

        print(f"\n  👤 角色选择 ({len(chars)} 个预置 + 快速创建):")
        for i, c in enumerate(chars, 1):
            print(f"  {i}. {c['name']}  ST{c['st']}/DX{c['dx']}/IQ{c['iq']}/HT{c['ht']}")
            if c.get('advantages'):
                print(f"     优势: {', '.join(c['advantages'][:2])}")

        print(f"  {len(chars)+1}. 快速创建默认角色（调查员）")
        print("  q. 返回")

        while True:
            choice = input("\n  请选择: ").strip().lower()
            if choice == "q":
                return None
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(chars):
                    return chars[idx]["file"]
                if idx == len(chars):
                    return "default"
            except ValueError:
                pass
            print("  ⚠️ 无效输入。")

    def run(self):
        """主入口"""
        self.show_splash()

        while True:
            mod = self.select_module()
            if mod is None:
                print("\n  感谢使用迷失之镜。再见。")
                break

            char = self.select_character()
            if char is None:
                continue

            print(f"\n  🚀 加载模组: {mod['title']}...")
            self._play(mod["path"], char)

    def _play(self, module_path: str, char_src: str):
        """游戏主循环"""
        from mirror_mvp import MirrorOfLost
        from core.character import Character
        from core.combat_engine import CombatEngine

        game = MirrorOfLost(SYSTEM_FILE, module_path)

        # 创建/加载角色
        if char_src == "default":
            pc = game.create_default_character()
        else:
            pc = Character.from_json(char_src)
        game.set_character(pc)

        # 显示开场
        act1 = game.module.get("act_1", {})
        self.renderer.render_intro(game.module.get("meta", {}).get("module_title", "未知模组"))
        mood = act1.get("environment", {}).get("mood", act1.get("description", ""))
        if mood:
            print(f"\n  {mood[:80]}")

        # 主循环
        current_combat = None

        while True:
            # 死亡检查
            if game.check_death():
                self.renderer.render_error("💀 你倒下了……")
                print("  [r] 重新开始  [m] 返回大厅  [q] 退出")
                choice = input("  请选择: ").strip().lower()
                if choice == "r":
                    if char_src == "default":
                        pc = game.create_default_character()
                    else:
                        pc = Character.from_json(char_src)
                    game.set_character(pc)
                    self.renderer.render_intro(game.module["meta"]["module_title"])
                    continue
                elif choice == "m":
                    break
                else:
                    return

            # 执念检查
            if game.check_obsession() and not getattr(game, '_obsession_shown', False):
                game._obsession_shown = True
                self.renderer.render_info(f"💀 你获得了永久执念：【{pc.obsession_name}】——从那以后，你再也无法直视任何反光表面……")

            # 状态栏
            self.renderer.render_status_bar(game.pc, game.env)

            # 获取可用节点
            available = game.get_available_nodes()

            # 检查游戏是否完成
            if not available:
                progress = game.get_progress()
                if progress.get("current_act") == "act_3" or game.is_game_over():
                    self._show_ending(game)
                    xp = game.get_xp_reward()
                    print(f"\n  ⭐ 获得 {xp} XP!")
                    print("  [m] 返回大厅  [q] 退出")
                    choice = input("  请选择: ").strip().lower()
                    if choice == "m":
                        break
                    return
                else:
                    self.renderer.render_info("当前没有可用场景。检查前置条件……")
                    # 列出所有未完成节点
                    all_done = True
                    for nid, node in game.engine._node_index.items():
                        if nid not in game.engine.completed_nodes:
                            prereq = node.get("prerequisite_nodes", [])
                            can = all(p in game.engine.completed_nodes for p in prereq)
                            status = "✅可用" if can else "🔒锁定"
                            print(f"    {nid} [{status}] 前置: {prereq}")
                    input("\n  按回车继续...")
                    continue

            # 动态行动菜单
            self.renderer.render_scene_menu(available, game.engine.completed_nodes)

            # 快捷键
            print("  c. 查看角色卡  |  s. 保存进度  |  h. 帮助")
            print("  m. 返回大厅   |  q. 退出")

            choice = input("\n  请选择: ").strip().lower()

            if choice == "q":
                return
            elif choice == "m":
                break
            elif choice == "h":
                self.renderer.render_help()
            elif choice == "c":
                self.renderer.render_character_sheet(game.pc)
            elif choice == "s":
                path = game.save_game()
                self.renderer.render_save_confirm(path)

            # 数字选择 = 场景
            else:
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(available):
                        node = available[idx]
                        nid = node["node_id"]
                        self.renderer.render_scene_header(node)

                        # 根据场景类型执行
                        scene_type = node.get("scene_type", "explore")

                        if scene_type == "combat":
                            self._handle_combat_scene(game, node)
                        else:
                            self._handle_check_scene(game, node)

                        # 场景结算
                        rewards = game.resolve_current_scene()
                        if rewards.get("focus_restored", 0) > 0 or rewards.get("marks_healed", 0) > 0:
                            self.renderer.render_settlement(rewards)

                    else:
                        self.renderer.render_error("编号超出范围。")
                except ValueError:
                    self.renderer.render_error("无效输入。")

    def _handle_check_scene(self, game, node: dict):
        """处理检定类场景"""
        # 先跑场景引擎获取 VM 结果
        vm_result = game.run_node(node["node_id"])

        # 渲染叙事
        self.renderer.render_resolution(vm_result)

        # 显示掷骰详情（从 packet 拦截——engine 内部掷骰）
        # 由于 engine.run_node 返回的是 ViewModelResult，需要额外的掷骰信息
        # 这里从 engine 获取最后一次掷骰
        if hasattr(game.engine, '_last_packet') and game.engine._last_packet:
            pkt = game.engine._last_packet
            emoji = "💥 大成功！" if pkt.get("is_crit_success") else ("💀 大失败！" if pkt.get("is_fumble") else
                   ("✓ 成功" if pkt.get("success") else "✗ 失败"))
            print(f"   🎲 掷出 {pkt.get('roll','?')}（目标 {pkt.get('target','?')}）— {emoji}")

        # 专注点动作
        if game.pc.focus_points > 0 and vm_result.available_focus_actions:
            print(f"\n   💡 专注点 ({game.pc.focus_points} 剩余)，是否使用？")
            for i, action in enumerate(vm_result.available_focus_actions[:3], 1):
                print(f"   {i}. ○ {action}")
            print("   0. 不使用")
            fc = input("   请选择: ").strip()
            if fc in ("1", "2", "3"):
                idx = int(fc) - 1
                if idx < len(vm_result.available_focus_actions):
                    action = vm_result.available_focus_actions[idx]
                    game.pc.spend_focus(1)
                    print(f"   ✨ 消耗 1 专注点！{action}")
                    # 触发特征
                    if "特征触发" in action:
                        feat_name = action.split("：")[1].split("(")[0].strip() if "：" in action else ""
                        for f in game.pc.features:
                            if f.name == feat_name:
                                f.used_this_scene += 1
                                print(f"   ⚡ 触发特征：【{f.name}】— {f.effect}")
                                break

    def _handle_combat_scene(self, game, node: dict):
        """处理战斗场景"""
        physics = node.get("layer_physics", {})
        stats = physics.get("unit_stats", {})
        special = physics.get("special_mechanic", {})

        enemy_name = stats.get("name", node.get("trigger", "未知敌人"))
        enemy_type = physics.get("enemy_type", "mook")

        print(f"\n⚔️  遭遇：{enemy_name} [{enemy_type}]")
        print("-" * 30)

        # 初始化战斗
        enemy_data = {
            "name": enemy_name,
            "enemy_type": "wildcard" if "wildcard" in enemy_type.lower() else "mook",
            "hp": stats.get("hp", 10),
            "hp_max": stats.get("hp", 10),
            "attack_skill": stats.get("attack_skill", 12),
            "damage": stats.get("damage", "1d6 cut"),
            "dodge": stats.get("dodge", 8),
            "dr": stats.get("dr", 0),
            "special_abilities": [special] if special else [],
        }

        game.start_combat(enemy_data)
        round_num = 0

        while not game.combat.is_combat_over():
            round_num += 1
            game.combat.start_round()
            print(f"\n--- 第 {round_num} 回合 ---")

            # 环境变化
            game.env.on_scene_tick()

            # 玩家回合
            if special and special.get("counter_play"):
                print(f"\n  🧠 特殊机制: {special.get('inversion', '')}")
                print(f"  破解方法: {special.get('counter_play', '')}")
                print("\n  行动选择:")
                print("  1. 普通攻击（⚠️有反射风险）")
                print(f"  2. 逆转攻击（消耗 1 专注点，破防 + 伤害x1.5）")
                if game.pc.focus_points > 0:
                    print(f"  3. 触发特征（消耗 1 专注点）")
                print("  f. 闪避（主动防御）")
            else:
                print(f"\n  行动选择:")
                print("  1. 普通攻击")
                if game.pc.focus_points > 0:
                    print(f"  2. 消耗专注点+2（剩余 {game.pc.focus_points}）")
                    print(f"  3. 触发特征")
                print("  f. 闪避")

            act = input("  请选择: ").strip().lower()

            skill_level = 14  # 默认
            weapons = game.pc.get_equipped_weapons()
            if weapons:
                sl = game.pc.get_skill_level("近战")
                if sl:
                    skill_level = sl

            is_reverse = False
            use_focus = False

            if act == "f":
                # 闪避——跳过攻击，等待敌人的回合
                defense = game.combat.active_defense(game.pc, {"damage": 0, "location": "躯干"})
                print(f"  🛡️ 你采取了防御姿态。")
            elif act == "2" and special and game.pc.spend_focus(1):
                is_reverse = True
                print(f"  ✨ 逆转攻击！专注点 -1（剩余 {game.pc.focus_points}）")
                packet = game.combat_player_attack(skill_level, is_reverse=True)
                if packet.get("success"):
                    packet["damage"] = int(packet.get("damage", 0) * 1.5)
                    self.renderer.render_combat_result(packet)
                    if packet.get("vm_result"):
                        print(f"  📖 {packet['vm_result'].narrative}")
                else:
                    self.renderer.render_combat_result(packet)
            elif act in ("2", "3") and game.pc.focus_points > 0 and not special:
                use_focus = True
                game.pc.spend_focus(1)
                skill_level += 2
                print(f"  ✨ 专注点+2（剩余 {game.pc.focus_points}）")
                packet = game.combat_player_attack(skill_level)
                self.renderer.render_combat_result(packet)
                if packet.get("vm_result"):
                    print(f"  📖 {packet['vm_result'].narrative}")
            elif act == "3" and special and game.pc.spend_focus(1):
                # 触发特征
                feat_triggered = False
                for f in game.pc.features:
                    if f.used_this_scene < f.per_scene_limit:
                        f.used_this_scene += 1
                        print(f"  ⚡ 触发特征：【{f.name}】— {f.effect}")
                        feat_triggered = True
                        break
                if not feat_triggered:
                    print("  ⚠️ 没有可触发的特征。")
                    game.pc.focus_points += 1  # 退回
            else:
                packet = game.combat_player_attack(skill_level)
                self.renderer.render_combat_result(packet)
                if packet.get("vm_result"):
                    print(f"  📖 {packet['vm_result'].narrative}")

                # 镜像反射检查
                if special and packet.get("success") and not is_reverse:
                    reflect = random.randint(1, 3)
                    game.pc.hp -= reflect
                    print(f"  🪞 镜像反射！受到 {reflect} 点伤害。HP: {game.pc.hp}/{game.pc.hp_max}")

            # 敌人回合
            if not game.combat.is_combat_over():
                ep = game.combat_enemy_attack()
                if ep.get("success"):
                    dmg = ep.get("damage", 0)
                    print(f"  🗡️ {enemy_name} 攻击！受到 {dmg} 点伤害。HP: {game.pc.hp}/{game.pc.hp_max}")
                else:
                    print(f"  {enemy_name} 攻击失误！")

            # 休克检查
            if game.pc.hp > 0:
                shock = game.combat.shock_check(game.pc, max(0, game.pc.hp_max - game.pc.hp))
                if shock.get("status") == "stunned":
                    print("  😵 震慑！下回合 -4 惩罚。")

            if game.check_death():
                break

        # 战斗结束
        if game.combat.get_pc_wins():
            print(f"\n  ✅ {enemy_name} 被击败！")
            game.engine.completed_nodes.add(node["node_id"])
        else:
            print(f"\n  💀 被{enemy_name}击败……")
            game.engine.completed_nodes.add(node["node_id"])

    def _show_ending(self, game):
        """显示结局"""
        marks = game.pc.psychic_marks
        print("\n" + "=" * 40)
        if marks <= 1:
            print("  🌅 好结局：重见天日")
            print("  镜屋巷的噩梦结束了。暴风雨已停，晨光洒落。")
            print("  你深吸一口气——是新鲜的、没有铜锈味的空气。")
        elif marks <= 3:
            print("  🌤️ 普通结局：阴影残留")
            print("  镜子碎了，但你知道它还在——在每一片反光里。")
            print("  你活着，但再也无法完全信任镜子里的自己。")
        else:
            print("  🌑 坏结局：镜痴")
            print("  你的身体走出来了。但灵魂还留在镜中。")
            print("  从那天起，你总在玻璃前停留太久……")
        print("=" * 40)
        print(f"\n  📊 HP {game.pc.hp}/{game.pc.hp_max} | 印记 {marks}")
        print(f"  专注点 {game.pc.focus_points} | 镜痴: {'是' if game.pc.has_obsession else '否'}")
        print("\n  🎉 感谢游玩《迷失之镜》！")


# ==================== 入口 ====================

if __name__ == "__main__":
    if "--create-template" in sys.argv:
        m = ModuleManager()
        MirrorLauncher().manager.create_template()
    else:
        MirrorLauncher().run()
