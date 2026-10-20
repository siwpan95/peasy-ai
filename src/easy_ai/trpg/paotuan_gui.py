"""
paotuan × easy-ai 深度整合 — 以 AI 为核心，跑团为训练场。

架构：
    AICore（大脑）← 学习 ← AITrainer ← 游戏事件
                                        ↑
    paotuan TRPG 引擎（教材）────────────┘

含义：跑团不是 AI 的"辅助系统"——跑团是 AI 的"训练方法"。
每场检定、每场战斗、每段叙事，都在教 AI 变得更聪明。

使用：
    python main.py paotuan
"""

import sys
import os
import json
import re
from typing import Dict, List, Optional, Any

# ---- 路径 ----
_EASYAI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PAOTUAN_DIR = os.path.join(_EASYAI_DIR, "paotuan")

# 命名空间包：easy_ai 自身已可导入，不再把包根塞进 sys.path
# easy-ai 的 ai.core 与 paotuan 的 core/ 不再冲突（ai.core vs core）
from easy_ai.ai.core import AICore
from easy_ai.ui.chat_ui import ChatUI
from easy_ai.trpg.trainer import AITrainer

# paotuan 必须在 easy-ai 之前（core/ 包 vs core.py 冲突）
# 注意：importlib 会自动往 sys.path[0] 插入路径，所以最后做
sys.path.insert(0, _PAOTUAN_DIR)


# ============================================================
# 场景 → UI 格式适配
# ============================================================
class _SceneAdapter:
    @staticmethod
    def adapt(node, engine, vm_result, combat=False):
        options = []
        choices = vm_result.choices if vm_result else []
        if combat:
            options = [{"text": t, "index": i, "action": a}
                       for i, (t, a) in enumerate([
                           ("攻击", "attack"), ("闪避防御", "defend"),
                           ("触发特征", "feature"), ("专注点", "focus")])]
        elif choices:
            options = [{"text": c.get("label",f"选项{i}"), "index": i,
                        "action": c.get("action","goto_node"),
                        "target": c.get("target")}
                       for i, c in enumerate(choices)]
        else:
            nexts = node.get("next_nodes", []) or []
            options = [{"text": engine._node_index.get(nid,{}).get("trigger",f"→{nid}"),
                        "index": i, "action": "goto_node", "target": nid}
                       for i, nid in enumerate(nexts)]

        pc = engine.pc
        attrs = {"HP": f"{pc.hp}/{pc.hp_max}", "FP": f"{pc.fp}/{pc.fp_max}",
                 "专注": f"{pc.focus_points}/{pc.focus_max}", "幸运": pc.luck_points}
        if pc.psychic_marks: attrs[f"印记{'×'*pc.psychic_marks}"] = pc.psychic_marks
        if engine.env and engine.env.tags:
            attrs["环境"] = ", ".join(t.get("name","") for t in engine.env.tags[:3])

        text = (vm_result.narrative if vm_result and vm_result.narrative
                else node.get("layer_narrative",{}).get("text",""))
        if vm_result and vm_result.available_focus_actions:
            text += "\n\n「专注」" + " / ".join(vm_result.available_focus_actions[:2])

        dice = ""
        if hasattr(engine,'_last_packet') and engine._last_packet:
            p = engine._last_packet
            dice = (f"命中 {p.get('roll','?')}/{p.get('target','?')} "
                    f"部位:{p.get('location','?')} 伤害:{p.get('damage','?')}"
                    if p.get("action_type")=="combat" else
                    f"检定 {'✓' if p.get('success') else '✗'} "
                    f"{p.get('roll','?')}/{p.get('target','?')}")

        enemy = None
        if combat and hasattr(engine,'combat_state') and engine.combat_state:
            e = engine.combat_state.get("enemy")
            if e: enemy = {"name": getattr(e,'name','?'),
                           "hp": getattr(e,'hp',0), "hp_max": getattr(e,'hp_max',0)}

        return {"type": "combat_start" if combat else "scene",
                "text": text, "dice_info": dice, "options": options,
                "attributes": attrs, "enemy": enemy}


# ============================================================
# PaotuanGUI — AI 大脑 + TRPG 教材
# ============================================================
class PaotuanGUI:
    """以 AICore 为核心，paotuan 引擎为训练场景。"""

    # ---- 初始化（种子知识） ----
    SEED_KNOWLEDGE = [
        ("这是什么游戏", "这是《迷失之镜》，一个基于 GURPS 4e 规则的恐怖跑团模组。"),
        ("3d6是什么", "GURPS 系统的核心掷骰方式：掷三个六面骰，总和 ≤ 技能等级即为成功，越低越好。"),
        ("什么是检定", "检定是判断角色行动成功与否的规则——用3d6掷骰，结果<=技能+修正即为成功。"),
        ("大成功是什么意思", "3d6掷出3或4为大成功，意味着行动超出预期的完美。"),
        ("大失败是什么意思", "3d6掷出17或18为大失败，意味着灾难性的后果。"),
        ("什么是专注点", "专注点是角色的精神资源——可用于声明细节、创造优势(+2)或改变环境。"),
        ("什么是精神印记", "精神印记代表角色受到的恐怖侵蚀。累积3个印记将触发执念——一种永久的精神创伤。"),
    ]

    def __init__(self, module_path: str = None, character_data: Dict = None):
        # 1. AI — 核心大脑
        self.ai = AICore(enable_session=True, enable_intent=True)
        self.trainer = AITrainer(self.ai)

        # 种子知识
        for q, a in self.SEED_KNOWLEDGE:
            self.trainer.on_manual_teach(q, a)

        # 2. 引擎 — 教材/训练场
        self._engine = self._init_engine(module_path, character_data)

        # 3. 角色知识
        if character_data:
            self.trainer.on_character_load(character_data)

        # 4. 规则知识
        self._teach_rule_knowledge()

        # 5. UI — 交互界面
        self._adapter = _SceneAdapter()
        self._cur_node = None
        self._combat = False
        self._pending: List[Dict] = []
        pc = self._engine.pc
        self._ui = ChatUI(
            title=f"AI 训练场 — {pc.name if pc else '学员'}",
            width=480, height=720,
            on_option=self._on_opt, on_free_text=self._on_txt,
            on_close=self._on_close)

    # ---- 引擎初始化 ----
    def _init_engine(self, mod_path, cd):
        _saved = {k: sys.modules.pop(k) for k in list(sys.modules)
                  if k=="core" or k.startswith("core.")}
        try:
            from mirror_mvp import MirrorOfLost
            from core.character import Character, Skill
        finally:
            for k in list(sys.modules):
                if k.startswith("core.") or (k=="core" and hasattr(sys.modules.get(k,None),"__path__")):
                    sys.modules.pop(k, None)
            sys.modules.update(_saved)

        sf = os.path.join(_PAOTUAN_DIR, "config", "system.json")
        if not mod_path:
            mod_path = os.path.join(_PAOTUAN_DIR, "modules", "mirror_house_alley", "module.json")
        eng = MirrorOfLost(sf, mod_path)

        if cd:
            try: pc = Character.from_dict(cd)
            except Exception:
                pc = Character(character_id=cd.get("character_id","custom"),
                    name=cd.get("name","调查员"), st=cd.get("st",10), dx=cd.get("dx",10),
                    iq=cd.get("iq",10), ht=cd.get("ht",10), skills=[],
                    advantages=cd.get("advantages",[]), disadvantages=cd.get("disadvantages",[]),
                    features=[], equipment=[], hp=cd.get("hp",cd.get("st",10)),
                    hp_max=cd.get("hp_max",cd.get("st",10)), fp=cd.get("fp",cd.get("ht",10)),
                    fp_max=cd.get("fp_max",cd.get("ht",10)),
                    will=cd.get("will",cd.get("iq",10)), per=cd.get("per",cd.get("iq",10)),
                    focus_points=cd.get("focus_points",3), focus_max=cd.get("focus_max",3),
                    luck_points=cd.get("luck_points",2), luck_max=cd.get("luck_max",2))
            eng.set_character(pc)
        else:
            eng.set_character(eng.create_default_character())
        return eng

    # ---- 规则知识种子 ----
    def _teach_rule_knowledge(self):
        """将 paotuan 系统配置转化为 AI 种子知识。"""
        cfg = self._engine.system
        # 锚点短语库中的关键概念
        anchors = cfg.get("content_libraries", {}).get("anchor_phrases", {})
        if anchors:
            self.trainer.on_rule_query("锚点短语系统",
                "锚点短语是 ViewModel 层的叙事转换规则——根据检定结果（成功/失败）和伤害类型（切割/穿刺/钝击），从锚点库中查找对应的叙事描述。")

        # 环境标签
        tags = self._engine.module.get("global_context_tags", [])
        if tags:
            tag_names = ", ".join(t.get("name","?") for t in tags[:3])
            self.trainer.on_rule_query("环境标签", f"当前模组的环境标签包括：{tag_names}。环境标签会影响检定修正值，玩家可用专注点改变环境。")

    # ---- 启动 ----
    def run(self):
        self._show_nodes()
        self._update_bar()
        pc = self._engine.pc
        self._ui._add_system_message(
            f"🧠 AI 训练场已启动\n"
            f"模组：《{self._engine.module.get('module_name','迷失之镜')}》\n"
            f"学员：{pc.name} ST{pc.st} DX{pc.dx} IQ{pc.iq} HT{pc.ht}\n"
            f"预训练：{self.trainer.trained_count} 条知识\n"
            f"每完成一个场景，AI 自动学习新知识。"
        )
        self._ui.run()

    # ---- 场景 ----
    def _show_nodes(self):
        nodes = self._engine.engine.get_available_nodes()
        if not nodes or self._engine.is_game_over():
            xp = self._engine.get_xp_reward()
            marks = self._engine.pc.psychic_marks
            self._ui.show_ending(
                f"冒险结束。\n经验值: {xp}\n精神印记: {marks}\n"
                f"\n🧠 训练统计：\n共学习 {self.trainer.trained_count} 条知识\n"
                f"AI 记忆库：{self.ai.memory_count} 个主题 / {self.ai.memory.total_answers} 条答案")
            return
        opts = []
        for n in nodes:
            nid = n.get("node_id","")
            st = n.get("scene_type","explore")
            ic = {"perception":"🔍","investigation":"📋","feat":"💪","combat":"⚔️","explore":"📍"}.get(st,"→")
            opts.append({"text": f"{ic} {n.get('trigger',nid)}",
                        "index": len(opts), "action": "enter", "node": nid})
        self._pending = []
        self._ui.show_scene("GM", None, f"选择探索方向（已学习 {self.trainer.trained_count} 条知识）：", opts)

    def _enter(self, nid):
        eng = self._engine.engine
        node = eng._node_index.get(nid)
        if not node: self._ui.add_ai_message(f"节点 {nid} 不存在。"); return
        self._cur_node = node
        eng.env.on_scene_enter(node)
        if node.get("scene_type") == "combat":
            self._combat_start(node); return

        vm = eng._handle_check_node(node)
        # ---- AI 自动学习 ----
        pkt = eng._last_packet
        if pkt and pkt.get("action_type") != "combat":
            self.trainer.on_scene_result(
                nid, pkt.get("skill_used","?"), pkt.get("roll",0),
                pkt.get("target",0), pkt.get("success",False),
                vm.narrative if vm else "")
        # ----
        r = self._adapter.adapt(node, eng, vm)
        txt = r["text"]
        if r.get("dice_info"): txt += f"\n「{r['dice_info']}」"
        ch = r.get("options",[])
        if ch:
            self._pending = ch
            self._ui.show_scene("检定结果", None, txt,
                               [{"text": c["text"], "index": c["index"]} for c in ch])
        else:
            self._ui.add_ai_message(txt)
            self._ui.after(500, self._show_nodes)
        self._update_bar()

    def _combat_start(self, node):
        eng = self._engine.engine
        vm = eng._handle_combat_node(node)
        self._combat = True
        r = self._adapter.adapt(node, eng, vm, combat=True)
        e = r.get("enemy",{})
        self._ui.show_scene(f"⚔ {e.get('name','?')}", None,
            f"{r['text']}\n\n{e.get('name','?')} HP:{e.get('hp','?')}/{e.get('hp_max','?')}",
            r["options"])
        self._update_bar()

    # ---- 回调 ----
    def _on_opt(self, idx):
        if self._combat: self._combat_act(idx); return
        pend = self._pending
        if 0 <= idx < len(pend):
            ch = pend[idx]
            if ch.get("action") == "goto_node" and ch.get("target"):
                self._engine.engine.completed_nodes.add(self._cur_node.get("node_id",""))
                self._pending = []
                self._enter(ch["target"]); return
        ns = self._engine.engine.get_available_nodes()
        if 0 <= idx < len(ns): self._enter(ns[idx].get("node_id",""))

    def _combat_act(self, idx):
        eng = self._engine; pc = eng.pc
        if idx == 0:
            w = pc.get_equipped_weapons(); s = w[0].get("skill_level",12) if w else 12
            p = eng.combat_player_attack(s)
            msg = "攻击！"
            if p:
                msg = f"攻击！「{p.get('roll','?')}/{p.get('target','?')} 伤害:{p.get('damage','?')}」"
                # AI 学习战斗
                self.trainer.on_combat_event(
                    getattr(eng.engine.combat_state.get("enemy",{}),"name","未知"),
                    getattr(eng.engine.combat_state.get("enemy",{}),"hp",0),
                    "攻击", p.get("damage",0), p.get("location",""),
                    getattr(eng.engine.combat_state.get("enemy",{}),"hp",0) <= 0)
            self._ui.add_ai_message(msg)
        elif idx == 1:
            self._ui.add_ai_message("闪避成功！" if eng.try_active_defense(eng.engine._last_packet) else "闪避失败...")
        elif idx == 2:
            f = pc.features; self._ui.add_ai_message(f"触发「{f[0].name}」：{f[0].effect}" if f else "无特征")
        elif idx == 3:
            self._ui.add_ai_message("可用专注动作：\n• 声明细节 • 创造优势(+2) • 环境互动")
        r = self._adapter.adapt(self._cur_node or {}, eng.engine, None, combat=True)
        self._ui.show_scene("⚔ 继续", None, "选择行动：", r["options"])
        self._update_bar()

    def _on_txt(self, text):
        if text.startswith("问：") or text.startswith("问:"):
            m = re.match(r'问[：:]\s*(.+?)\s*答[：:]\s*(.+)', text)
            if m:
                q, a = m.groups()
                self.trainer.on_manual_teach(q, a)
                self._ui.add_ai_message(f"🧠 学会了！「{q}」→「{a}」\n已训练 {self.trainer.trained_count} 条。")
                return
        if any(k in text for k in ["HP","状态","角色","属性"]):
            pc = self._engine.pc
            self._ui.add_ai_message(f"[{pc.name}] HP:{pc.hp}/{pc.hp_max} FP:{pc.fp}/{pc.fp_max} "
                f"ST:{pc.st} DX:{pc.dx} IQ:{pc.iq} HT:{pc.ht} "
                f"专注:{pc.focus_points} 印记:{pc.psychic_marks}"
                f"\n🧠 AI 已学习 {self.trainer.trained_count} 条知识。")
            return
        if "帮助" in text or "/help" in text:
            self._ui.add_ai_message(
                "🧠 AI 训练场\n• 点击场景按钮 → 执行检定（AI 自动学习）\n"
                "• 输入文字 → 与 AI 对话\n• 问：问题 答：答案 → 手动教学\n"
                "• 输入 /stats → 查看 AI 训练统计")
            return
        if text == "/stats":
            s = self.trainer.summary
            self._ui.add_ai_message(
                f"🧠 训练统计\n• 已学习: {s['total']} 条\n"
                f"• AI 记忆: {s['ai_memory']} 主题 / {s['ai_answers']} 条答案\n"
                f"• 来源: {s['by_source']}")
            return
        if text == "/export":
            path = os.path.join(_EASYAI_DIR, "training_log.json")
            self.trainer.export_training_log(path)
            self._ui.add_ai_message(f"训练日志已导出: {path}")
            return
        # AI 闲聊
        self._ui.add_ai_message(self.ai.respond(text))

    def _update_bar(self):
        pc = self._engine.pc
        a = {"HP": int(pc.hp/pc.hp_max*100) if pc.hp_max else 0,
             "FP": int(pc.fp/pc.fp_max*100) if pc.fp_max else 0,
             "专注": int(pc.focus_points/pc.focus_max*100) if pc.focus_max else 0}
        if pc.psychic_marks: a["印记"] = pc.psychic_marks * 33
        self._ui.show_attributes(a, {k:100 for k in a})

    def _on_close(self):
        if self.trainer.trained_count > 0:
            p = os.path.join(_EASYAI_DIR, "training_log.json")
            self.trainer.export_training_log(p)
            print(f"\n🧠 训练日志已保存: {p}")


# ============================================================
# 入口
# ============================================================
def scan_paotuan_resources():
    chars = []
    cd = os.path.join(_PAOTUAN_DIR, "characters")
    if os.path.isdir(cd):
        for fn in sorted(os.listdir(cd)):
            if fn.endswith(".json"):
                try:
                    with open(os.path.join(cd, fn), encoding="utf-8") as f: d=json.load(f)
                    chars.append({"name": d.get("name",fn), "id": d.get("character_id",fn),
                                  "path": os.path.join(cd, fn), "st": d.get("st",10),
                                  "dx": d.get("dx",10), "iq": d.get("iq",10), "ht": d.get("ht",10)})
                except (json.JSONDecodeError, OSError):
                    pass
    mods = []
    md = os.path.join(_PAOTUAN_DIR, "modules")
    if os.path.isdir(md):
        for dn in sorted(os.listdir(md)):
            dp = os.path.join(md, dn); mp = os.path.join(dp, "module.json")
            if os.path.isdir(dp) and os.path.exists(mp):
                try:
                    with open(mp, encoding="utf-8") as f: d=json.load(f)
                    mods.append({"name": d.get("module_name",dn), "id": dn, "path": mp,
                                "acts": len([k for k in d if k.startswith("act_")])})
                except (json.JSONDecodeError, OSError):
                    pass
    return {"valid": bool(chars or mods), "characters": chars, "modules": mods}


def run_paotuan_gui(module_path: str = None, character_file: str = None):
    cd = None
    if character_file and os.path.exists(character_file):
        with open(character_file, encoding="utf-8") as f: cd = json.load(f)
    PaotuanGUI(module_path=module_path, character_data=cd).run()


if __name__ == "__main__":
    run_paotuan_gui()
