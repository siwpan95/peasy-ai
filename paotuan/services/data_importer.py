# -*- coding: utf-8 -*-
"""
迷失之镜 — 统一导入器 (Model 层 · 阶段 2)
==========================================
覆盖角色卡(JSON)、敌人(JSON/Excel)、物品(JSON/Excel)、
陷阱(Excel)、遭遇表(Excel)、战利品表(Excel)、
NPC反应表(Excel)、场景构建表(Excel→module.json)、网格地图

管线: Excel 填表 → 本模块读表 → JSON → 引擎消费
"""
import json
import os
from typing import List, Dict, Optional
from core.character import Character, Skill, CharacterFeature, Equipment
from core.enemy import Enemy

# 项目根目录（pt/）
_PT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class DataImporter:
    """统一数据导入器 — 支持 JSON 和 Excel 两种输入"""

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = _PT_DIR
        self.base_dir = base_dir

    # ================================================================
    #  角色卡导入（JSON）
    # ================================================================

    def import_character(self, json_path: str) -> Optional[Character]:
        """从 JSON 文件导入角色"""
        return Character.from_json(json_path)

    def import_characters_dir(self, chars_dir: str = None) -> List[Character]:
        """批量导入角色目录"""
        if chars_dir is None:
            chars_dir = os.path.join(_PT_DIR, "characters")
        characters = []
        path = os.path.join(self.base_dir, chars_dir)
        if not os.path.isdir(path):
            return characters

        for filename in sorted(os.listdir(path)):
            if filename.endswith(".json"):
                char = self.import_character(os.path.join(path, filename))
                if char:
                    characters.append(char)
        return characters

    # ================================================================
    #  敌人导入（JSON + Excel）
    # ================================================================

    def import_enemies(self, json_path: str) -> List[Enemy]:
        """从 JSON 导入敌人库"""
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        enemies = []
        items = data if isinstance(data, list) else data.get("enemies", [])
        for item in items:
            enemies.append(Enemy.from_dict(item))
        return enemies

    def import_enemies_from_xlsx(self, xlsx_path: str) -> List[Dict]:
        """从 enemy_builder.xlsx 导入敌人 → JSON dict 列表"""
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ImportError("需要 openpyxl 库: pip install openpyxl")

        wb = load_workbook(xlsx_path, data_only=True)
        ws = wb.active
        enemies = []

        for row in ws.iter_rows(min_row=4, max_col=21, values_only=True):
            if row[0] is None or str(row[0]).strip() == "":
                continue
            name = str(row[0]).strip()

            enemy = {
                "name": name,
                "enemy_type": str(row[1]).strip() if row[1] else "mook",
                "hp": int(row[2]) if row[2] else 10,
                "hp_max": int(row[3]) if row[3] else 10,
                "attack_skill": int(row[9]) if row[9] else 10,
                "damage": str(row[10]) if row[10] else "1d6 cut",
                "dodge": int(row[11]) if row[11] else 8,
                "dr": int(row[12]) if row[12] else 0,
                "description": str(row[13]) if row[13] else "",
                "flavor_text": str(row[14]) if row[14] else "",
            }

            # 可选字段
            if row[4]: enemy["fp"] = int(row[4])
            if row[5]: enemy["st"] = int(row[5])
            if row[6]: enemy["dx"] = int(row[6])
            if row[7]: enemy["iq"] = int(row[7])
            if row[8]: enemy["ht"] = int(row[8])

            # 特殊能力
            special = []
            if row[15] and str(row[15]).strip():
                ability = {"name": str(row[15]).strip()}
                if row[16]: ability["effect"] = str(row[16]).strip()
                if row[17]: ability["trigger"] = str(row[17]).strip()
                special.append(ability)
            if special:
                enemy["special_abilities"] = special

            # 附庸阈值
            threshold = {}
            if row[18] and str(row[18]).strip():
                threshold[">=6"] = str(row[18]).strip()
            if row[19] and str(row[19]).strip():
                threshold["2-5"] = str(row[19]).strip()
            if row[20] and str(row[20]).strip():
                threshold["<2"] = str(row[20]).strip()
            if threshold:
                enemy["minion_threshold"] = threshold

            enemies.append(enemy)

        wb.close()
        return enemies

    def import_enemies_from_xlsx_and_save(self, xlsx_path: str, output_path: str = None):
        """从 Excel 导入敌人并保存为 JSON"""
        enemies = self.import_enemies_from_xlsx(xlsx_path)
        if output_path is None:
            output_path = os.path.join(self.base_dir, "data", "enemies.json")
        data = {"enemies": enemies}
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return output_path

    # ================================================================
    #  物品导入（JSON + Excel）
    # ================================================================

    def import_items(self, json_path: str) -> Dict:
        """从 JSON 导入物品库"""
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def import_items_from_xlsx(self, xlsx_path: str) -> Dict:
        """从 item_builder.xlsx 导入物品 → JSON dict"""
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ImportError("需要 openpyxl 库: pip install openpyxl")

        wb = load_workbook(xlsx_path, data_only=True)
        ws = wb.active
        items = {}

        for row in ws.iter_rows(min_row=4, max_col=12, values_only=True):
            if row[0] is None or str(row[0]).strip() == "":
                continue
            item_id = str(row[0]).strip()
            name = str(row[1]) if row[1] else item_id

            effects = []
            if row[7] and str(row[7]).strip() and row[8] and str(row[8]).strip():
                eff_type = str(row[7]).strip()
                eff_val = str(row[8]).strip()
                if eff_type == "restore_hp":
                    effects.append({"restore_hp": eff_val})
                elif eff_type == "restore_fp":
                    effects.append({"restore_fp": eff_val})
                elif eff_type == "tag_mod":
                    effects.append({"tag_mod": eff_val})
                elif eff_type == "tool_bonus":
                    parts = eff_val.split(":")
                    if len(parts) == 2:
                        effects.append({"tool_bonus": int(parts[1]), "skill": parts[0]})
                elif eff_type == "penalty":
                    parts = eff_val.split(":")
                    if len(parts) == 2:
                        effects.append({"penalty": {parts[0]: int(parts[1])}})
                elif eff_type == "psychic_resistance":
                    effects.append({"psychic_resistance": int(eff_val)})

            item = {
                "name": name,
                "type": str(row[2]).strip() if row[2] else "tool",
                "slot": str(row[3]).strip() if row[3] else "backpack",
                "description": str(row[10]) if row[10] else "",
            }

            if row[4] and int(row[4]) > 0:
                item["dr"] = int(row[4])
            if row[5] and str(row[5]).strip():
                item["dr_location"] = str(row[5]).strip()
            if row[6] and str(row[6]).strip():
                item["damage"] = str(row[6]).strip()
            if effects:
                item["effects"] = effects
            if row[9] is not None:
                item["uses"] = int(row[9])

            items[item_id] = item

        wb.close()
        return items

    def import_items_from_xlsx_and_save(self, xlsx_path: str, output_path: str = None):
        """从 Excel 导入物品并保存为 JSON"""
        items = self.import_items_from_xlsx(xlsx_path)
        if output_path is None:
            output_path = os.path.join(self.base_dir, "data", "items.json")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        return output_path

    # ================================================================
    #  陷阱导入（Excel）
    # ================================================================

    def import_traps_from_xlsx(self, xlsx_path: str) -> List[Dict]:
        """从 trap_builder.xlsx 导入陷阱"""
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ImportError("需要 openpyxl 库: pip install openpyxl")

        wb = load_workbook(xlsx_path, data_only=True)
        ws = wb.active
        traps = []

        for row in ws.iter_rows(min_row=4, max_col=10, values_only=True):
            if row[0] is None or str(row[0]).strip() == "":
                continue
            trap = {
                "id": str(row[0]).strip(),
                "name": str(row[1]) if row[1] else "",
                "trigger": str(row[2]) if row[2] else "",
                "detect_skill": str(row[3]) if row[3] else "Per",
                "detect_dc": int(row[4]) if row[4] else 10,
                "effect": str(row[5]) if row[5] else "",
                "damage": str(row[6]) if row[6] else "",
                "disarm_skill": str(row[7]) if row[7] else "",
                "disarm_dc": int(row[8]) if row[8] else 10,
                "notes": str(row[9]) if row[9] else "",
            }
            traps.append(trap)

        wb.close()
        return traps

    # ================================================================
    #  随机遭遇表导入（Excel）
    # ================================================================

    def import_encounters_from_xlsx(self, xlsx_path: str) -> List[Dict]:
        """从 encounter_table.xlsx 导入遭遇表"""
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ImportError("需要 openpyxl 库: pip install openpyxl")

        wb = load_workbook(xlsx_path, data_only=True)
        ws = wb.active
        encounters = []

        for row in ws.iter_rows(min_row=4, max_col=9, values_only=True):
            if row[0] is None or str(row[0]).strip() == "":
                continue
            enc = {
                "area": str(row[0]).strip(),
                "roll_min": int(row[1]) if row[1] else 1,
                "roll_max": int(row[2]) if row[2] else 100,
                "content": str(row[3]) if row[3] else "",
                "enemy_ref": str(row[4]) if row[4] else "",
                "difficulty": str(row[5]) if row[5] else "",
                "count": str(row[6]) if row[6] else "",
                "loot": str(row[7]) if row[7] else "",
                "notes": str(row[8]) if row[8] else "",
            }
            encounters.append(enc)

        wb.close()
        return encounters

    # ================================================================
    #  战利品表导入（Excel）
    # ================================================================

    def import_loot_from_xlsx(self, xlsx_path: str) -> List[Dict]:
        """从 loot_table.xlsx 导入战利品表"""
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ImportError("需要 openpyxl 库: pip install openpyxl")

        wb = load_workbook(xlsx_path, data_only=True)
        ws = wb.active
        loots = []

        for row in ws.iter_rows(min_row=4, max_col=8, values_only=True):
            if row[0] is None or str(row[0]).strip() == "":
                continue
            loot = {
                "source": str(row[0]).strip(),
                "roll_min": int(row[1]) if row[1] else 1,
                "roll_max": int(row[2]) if row[2] else 100,
                "item_id": str(row[3]) if row[3] else "",
                "count": str(row[4]) if row[4] else "1",
                "quality": str(row[5]) if row[5] else "",
                "description": str(row[6]) if row[6] else "",
                "notes": str(row[7]) if row[7] else "",
            }
            loots.append(loot)

        wb.close()
        return loots

    # ================================================================
    #  NPC 反应表导入（Excel）
    # ================================================================

    def import_reactions_from_xlsx(self, xlsx_path: str) -> List[Dict]:
        """从 npc_reaction.xlsx 导入 NPC 反应表"""
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ImportError("需要 openpyxl 库: pip install openpyxl")

        wb = load_workbook(xlsx_path, data_only=True)
        ws = wb.active
        reactions = []

        for row in ws.iter_rows(min_row=4, max_col=7, values_only=True):
            if row[0] is None or str(row[0]).strip() == "":
                continue
            react = {
                "roll_range": str(row[0]).strip(),
                "attitude": str(row[1]) if row[1] else "",
                "behavior": str(row[2]) if row[2] else "",
                "negotiate_modifier": str(row[3]) if row[3] else "",
                "combat_willingness": str(row[4]) if row[4] else "",
                "help_willingness": str(row[5]) if row[5] else "",
                "notes": str(row[6]) if row[6] else "",
            }
            reactions.append(react)

        wb.close()
        return reactions

    # ================================================================
    #  场景构建表 → module.json（Excel）
    # ================================================================

    def import_scenes_from_xlsx(self, xlsx_path: str) -> Dict:
        """从 scene_builder.xlsx 导入场景数据 → module dict"""
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ImportError("需要 openpyxl 库: pip install openpyxl")

        wb = load_workbook(xlsx_path, data_only=True)
        module = {"meta": {}, "global_context_tags": [], "gm_cheatsheet": {"quick_ref_table": []}}

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            nodes = []
            act_title = sheet_name.replace("Act1_", "").replace("Act2_", "").replace("Act3_", "")
            act_key = None

            if "Act1" in sheet_name or "第一幕" in act_title:
                act_key = "act_1"
                act_id = "act1_opening"
            elif "Act2" in sheet_name or "第二幕" in act_title:
                act_key = "act_2"
                act_id = "act2_conflict"
            elif "Act3" in sheet_name or "第三幕" in act_title:
                act_key = "act_3"
                act_id = "act3_climax"
            else:
                continue

            for row in ws.iter_rows(min_row=4, max_col=33, values_only=True):
                if row[0] is None or str(row[0]).strip() == "":
                    continue

                node_id = str(row[0]).strip()
                scene_type = str(row[1]).strip() if row[1] else "explore"
                trigger = str(row[2]) if row[2] else ""

                # 前置/后续节点解析
                pre_str = str(row[3]) if row[3] else ""
                pre_nodes = [x.strip() for x in pre_str.split("|") if x.strip()] if pre_str else []
                next_str = str(row[4]) if row[4] else ""
                next_nodes = [x.strip() for x in next_str.split("|") if x.strip()] if next_str else []

                node = {
                    "node_id": node_id,
                    "scene_type": scene_type,
                    "trigger": trigger,
                    "prerequisite_nodes": pre_nodes,
                    "next_nodes": next_nodes,
                    "layer_physics": {},
                    "layer_narrative": {
                        "anchor_phrases": {}
                    },
                    "layer_pacing": {},
                }

                # 叙事锚点
                if row[6] and str(row[6]).strip():
                    node["layer_narrative"]["anchor_phrases"]["success"] = str(row[6]).strip()
                if row[7] and str(row[7]).strip():
                    node["layer_narrative"]["anchor_phrases"]["failure"] = str(row[7]).strip()
                if row[8] and str(row[8]).strip():
                    node["layer_narrative"]["anchor_phrases"]["crit_success"] = str(row[8]).strip()

                # 检定配置
                if row[5] and str(row[5]).strip():
                    node["layer_physics"]["skill_check"] = str(row[5]).strip()
                if row[6] is not None and isinstance(row[6], (int, float)):
                    node["layer_physics"]["modifier"] = int(row[6])

                # 嵌套检定
                if scene_type == "investigation" and row[10] and str(row[10]).strip():
                    nested = {
                        "skill": str(row[10]).strip(),
                        "result": str(row[11]) if row[11] else "",
                    }
                    if row[12] and str(row[12]).strip():
                        nested["flag"] = str(row[12]).strip()
                    node["layer_physics"]["skill_checks"] = [nested]

                # 战斗配置
                if scene_type == "combat":
                    combat_unit = {}
                    if row[13] and str(row[13]).strip():
                        combat_unit["enemy_type"] = str(row[13]).strip()
                    if row[14] and str(row[14]).strip():
                        combat_unit["name"] = str(row[14]).strip()
                    if row[15] is not None:
                        combat_unit["attack_skill"] = int(row[15])
                    if row[16] and str(row[16]).strip():
                        combat_unit["damage"] = str(row[16]).strip()
                    if row[17] is not None:
                        combat_unit["dodge"] = int(row[17])
                    if row[18] is not None:
                        combat_unit["hp"] = int(row[18])
                    if row[19] is not None:
                        combat_unit["dr"] = int(row[19])
                    node["layer_physics"]["unit_stats"] = combat_unit

                    # 特殊机制
                    if row[20] and str(row[20]).strip():
                        node["layer_physics"]["special_mechanic"] = {
                            "name": str(row[20]).strip(),
                            "effect": str(row[21]) if row[21] else "",
                            "counter_play": str(row[22]) if row[22] else "",
                        }

                # 印记
                if row[23] and str(row[23]).strip():
                    try:
                        failure_cost = int(row[25]) if row[25] and str(row[25]).strip() and str(row[25]).strip().lstrip("-").isdigit() else 1
                    except (ValueError, TypeError):
                        failure_cost = 1
                    node["psychic_marks"] = {
                        "trigger_level": str(row[23]).strip(),
                        "check": str(row[24]) if row[24] else "",
                        "failure_cost": failure_cost,
                        "effect_description": str(row[26]) if row[26] else "",
                    }

                # Flags
                if row[27] and str(row[27]).strip():
                    node["set_flag"] = str(row[27]).strip()
                if row[28] and str(row[28]).strip():
                    node["clear_flag"] = str(row[28]).strip()

                # 环境标签
                if row[29] and str(row[29]).strip():
                    node["environment_tags_add"] = str(row[29]).strip()
                if row[30] and str(row[30]).strip():
                    node["environment_tags_remove"] = str(row[30]).strip()

                # 节奏
                if row[31] and str(row[31]).strip():
                    node["layer_pacing"]["initiative"] = str(row[31]).strip()
                if row[32] and str(row[32]).strip():
                    node["layer_pacing"]["time_pressure"] = str(row[32]).strip()

                nodes.append(node)

            if act_key:
                module[act_key] = {
                    "scene_id": act_id,
                    "title": act_title,
                    "description": "",
                    "nodes": nodes,
                }

        wb.close()
        return module

    def import_scenes_from_xlsx_and_save(self, xlsx_path: str, output_path: str, meta: Dict = None):
        """从 Excel 导入场景并保存为 module.json"""
        module = self.import_scenes_from_xlsx(xlsx_path)
        if meta:
            module["meta"] = meta
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(module, f, ensure_ascii=False, indent=2)
        return output_path

    # ================================================================
    #  场景 JSON → module.json（保留向后兼容）
    # ================================================================

    def import_scenes_to_module(self, json_path: str, output_path: str):
        """从场景数据 JSON 生成 module.json（向后兼容）"""
        with open(json_path, "r", encoding="utf-8") as f:
            scene_data = json.load(f)

        module = {
            "meta": scene_data.get("meta", {}),
            "global_context_tags": scene_data.get("global_context_tags", []),
            "act_1": self._build_act(scene_data.get("act_1", []), "act1_opening", "第一幕"),
            "act_2": self._build_act(scene_data.get("act_2", []), "act2_conflict", "第二幕"),
            "act_3": self._build_act(scene_data.get("act_3", []), "act3_climax", "第三幕"),
            "gm_cheatsheet": scene_data.get("gm_cheatsheet", {"quick_ref_table": []}),
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(module, f, ensure_ascii=False, indent=2)

        return output_path

    def _build_act(self, scenes: List[Dict], scene_id: str, title: str) -> Dict:
        """构建一幕"""
        nodes = []
        for sc in scenes:
            node = {
                "node_id": sc.get("node_id", ""),
                "scene_type": sc.get("scene_type", "explore"),
                "trigger": sc.get("trigger", ""),
                "prerequisite_nodes": sc.get("prerequisite_nodes", []),
                "next_nodes": sc.get("next_nodes", []),
                "layer_physics": sc.get("layer_physics", {}),
                "layer_narrative": sc.get("layer_narrative", {}),
            }
            if sc.get("psychic_marks"):
                node["psychic_marks"] = sc["psychic_marks"]
            nodes.append(node)

        return {
            "scene_id": scene_id,
            "title": title,
            "description": "",
            "nodes": nodes,
        }

    # ================================================================
    #  批量导入
    # ================================================================

    def import_all(self, data_dir: str = None):
        """批量导入所有 JSON 数据"""
        if data_dir is None:
            data_dir = os.path.join(_PT_DIR, "data")
        results = {}
        path = os.path.join(self.base_dir, data_dir)

        enemy_file = os.path.join(path, "enemies.json")
        if os.path.exists(enemy_file):
            results["enemies"] = self.import_enemies(enemy_file)

        item_file = os.path.join(path, "items.json")
        if os.path.exists(item_file):
            results["items"] = self.import_items(item_file)

        return results

    def import_all_from_excel(self, templates_dir: str = None):
        """批量从 Excel 模板导入所有数据 → JSON"""
        if templates_dir is None:
            templates_dir = os.path.join(_PT_DIR, "templates")
        results = {}

        mapping = [
            ("enemy_builder.xlsx", "import_enemies_from_xlsx", "enemies"),
            ("item_builder.xlsx", "import_items_from_xlsx", "items"),
            ("trap_builder.xlsx", "import_traps_from_xlsx", "traps"),
            ("encounter_table.xlsx", "import_encounters_from_xlsx", "encounters"),
            ("loot_table.xlsx", "import_loot_from_xlsx", "loot"),
            ("npc_reaction.xlsx", "import_reactions_from_xlsx", "reactions"),
        ]

        for fname, method_name, key in mapping:
            xlsx_path = os.path.join(templates_dir, fname)
            if os.path.exists(xlsx_path):
                method = getattr(self, method_name)
                results[key] = method(xlsx_path)
                print(f"  ✅ {fname} → {len(results[key])} 条记录")

        return results
