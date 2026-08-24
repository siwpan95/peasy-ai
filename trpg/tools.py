"""
TRPG 工具箱：AI 辅助跑团的功能模块。

基于对 2025-2026 年 AI+TRPG 最佳实践的研究，提供：
- 1. 骰子解析与掷骰 (DiceRoller)
- 2. 随机表生成 (RandomTables) — NPC/遭遇/战利品/天气
- 3. 程序化内容生成 (ProceduralGen) — 名字/地点/宝物/任务
- 4. 战报日记 (CampaignJournal) — 会话记录与回顾

全部零外部依赖。设计参考 GameMaster-GPT、D&D-AI、Archivist。
"""

import random
import re
import json
import os
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime


# ============================================================
# 1. 骰子解析与掷骰
# ============================================================
class DiceRoller:
    """解析并掷骰。支持 D&D / GURPS 等多种格式。

    用法：
        DiceRoller.roll("3d6")       → (11, [4, 2, 5])
        DiceRoller.roll("2d8+3")     → (13, [5, 5], "+3")
        DiceRoller.roll("d20")       → (15, [15])
        DiceRoller.roll("4d6k3")     → (14, [6, 5, 3, 2], "drop 2")
        DiceRoller.roll("2d6!")      → (18, [6, 6, 4, 2], "exploded")
    """

    DICE_PATTERN = re.compile(
        r'(?:(?P<count>\d+))?d(?P<sides>\d+)'
        r'(?P<keep>k(?P<keep_n>\d+))?'
        r'(?P<explode>!)?'
        r'(?:(?P<mod_op>[+-])(?P<mod_val>\d+))?'
    )

    @classmethod
    def roll(cls, notation: str) -> Tuple[int, List[int], str]:
        """掷骰。

        Returns:
            (total, individual_results, modifier_description)
        """
        m = cls.DICE_PATTERN.match(notation.lower().replace(" ", ""))
        if not m:
            return (0, [], f"无效骰子表达式: {notation}")

        count = int(m.group("count")) if m.group("count") else 1
        sides = int(m.group("sides"))
        keep_n = int(m.group("keep_n")) if m.group("keep_n") else None
        explode = bool(m.group("explode"))
        mod_op = m.group("mod_op")
        mod_val = int(m.group("mod_val")) if m.group("mod_val") else 0

        if count > 100 or sides > 1000:
            return (0, [], "骰子数量/面数过大")

        # 掷骰
        results = []
        for _ in range(count):
            r = random.randint(1, sides)
            results.append(r)
            # 爆炸骰
            if explode:
                while r == sides:
                    r = random.randint(1, sides)
                    results.append(r)

        # Keep N highest
        desc = ""
        if keep_n and keep_n < len(results):
            results.sort(reverse=True)
            desc = f"drop {len(results) - keep_n}"
            results = results[:keep_n]

        # 修正值
        total = sum(results)
        if mod_op == "+":
            total += mod_val
            desc = f"{desc}+{mod_val}".lstrip(" ")
        elif mod_op == "-":
            total -= mod_val
            desc = f"{desc}-{mod_val}".lstrip(" ")

        return (total, results, desc or "plain")

    @classmethod
    def roll_gurps(cls, skill_level: int, modifier: int = 0) -> Dict[str, Any]:
        """GURPS 3d6 检定。"""
        total, dice, _ = cls.roll("3d6")
        target = skill_level + modifier
        success = total <= target
        margin = target - total
        is_crit = total <= 4 or (total <= 6 and skill_level >= 15)
        is_fumble = total >= 17 or (total == 18)

        return {
            "roll": total,
            "dice": dice,
            "target": target,
            "success": success,
            "margin": margin,
            "is_critical": is_crit,
            "is_fumble": is_fumble,
        }

    @classmethod
    def roll_advantage(cls, sides: int = 20) -> Tuple[int, List[int]]:
        """D&D 优势掷骰。"""
        a = random.randint(1, sides)
        b = random.randint(1, sides)
        return max(a, b), [a, b]

    @classmethod
    def roll_disadvantage(cls, sides: int = 20) -> Tuple[int, List[int]]:
        """D&D 劣势掷骰。"""
        a = random.randint(1, sides)
        b = random.randint(1, sides)
        return min(a, b), [a, b]


# ============================================================
# 2. 随机表生成器
# ============================================================
class RandomTables:
    """预置随机表 + 可自定义扩展。零外部依赖。"""

    # ---- NPC 名字 ----
    NPC_FIRST_NAMES = [
        "艾琳", "塞德里克", "莉安娜", "加雷斯", "伊莎贝尔",
        "奥利弗", "菲奥娜", "马库斯", "索菲亚", "雷克斯",
        "莉莉丝", "凯恩", "诺拉", "文森特", "格温",
    ]
    NPC_LAST_NAMES = [
        "铁锤", "灰袍", "渡鸦", "石盾", "银叶",
        "黑木", "风暴", "龙心", "霜语", "暗影",
    ]
    NPC_TRAITS = [
        "沉默寡言", "热情豪爽", "疑心重重", "健忘迷糊",
        "精明狡猾", "正直固执", "幽默风趣", "冷酷无情",
        "好奇心强", "胆小谨慎",
    ]
    NPC_OCCUPATIONS = [
        "酒馆老板", "铁匠", "草药师", "守卫队长", "旅行商人",
        "图书管理员", "赏金猎人", "街头艺人", "炼金术士", "船夫",
    ]

    # ---- 遭遇 ----
    URBAN_ENCOUNTERS = [
        "一个小偷试图扒窃你的钱包", "街头艺人正在表演神奇的戏法",
        "商人在叫卖稀有商品", "守卫正在盘查过路行人",
        "流浪儿童请求施舍", "两个帮派在巷子里对峙",
        "传令官宣读新的法令", "神秘人递给你一张纸条后匆匆离开",
    ]
    WILDERNESS_ENCOUNTERS = [
        "一群野狼在远处嚎叫", "奇怪的蘑菇在树根下发出微光",
        "废弃的营地还有余烬", "一只受伤的鹿倒在路边",
        "巨大的脚印通向密林深处", "雷声滚滚，暴风雨即将来临",
        "古老的石碑半埋在土中", "树上有刻痕标记，似乎是某种路标",
    ]
    DUNGEON_ENCOUNTERS = [
        "地面突然塌陷露出暗洞", "墙上的火炬突然全部熄灭",
        "骷髅从石棺中爬出", "机关陷阱被触发——毒箭齐射",
        "低语声从墙壁后传来", "一扇秘门缓缓打开",
        "地上的血迹还很新鲜", "宝箱静静地放在房间中央",
    ]

    # ---- 战利品 ----
    LOOT_TABLES = {
        "poor": ["几枚铜币", "破旧的匕首", "发霉的面包", "一截绳子", "空瓶子"],
        "common": ["银币×10", "治疗药水", "精制短剑", "魔法卷轴(1级)", "旅人干粮×3"],
        "uncommon": ["金币×50", "+1 武器", "抗性戒指", "隐形药水", "元素宝石"],
        "rare": ["金币×200", "+2 武器", "龙鳞甲", "传送卷轴", "凤凰羽毛"],
        "legendary": ["+3 传说武器", "许愿戒指", "时光沙漏", "龙蛋", "神祇护符"],
    }

    # ---- 天气 ----
    WEATHER_TABLES = {
        "temperate": ["晴朗", "多云", "小雨", "大风", "薄雾", "雷阵雨"],
        "desert": ["酷热", "沙尘暴", "干燥", "烈日", "夜晚严寒"],
        "arctic": ["暴风雪", "极寒", "冰雹", "薄雪", "晴朗但刺骨"],
        "coastal": ["海风", "大雾", "暴风雨", "晴朗", "毛毛雨"],
    }

    @classmethod
    def npc_name(cls) -> str:
        """随机 NPC 名字。"""
        return f"{random.choice(cls.NPC_FIRST_NAMES)}·{random.choice(cls.NPC_LAST_NAMES)}"

    @classmethod
    def npc_full(cls) -> Dict[str, str]:
        """随机完整 NPC。"""
        return {
            "name": cls.npc_name(),
            "trait": random.choice(cls.NPC_TRAITS),
            "occupation": random.choice(cls.NPC_OCCUPATIONS),
            "mood": random.choice(["友善", "中立", "警惕", "敌意", "恐惧"]),
            "secret": random.choice([
                "欠了赌债", "是秘密组织成员", "知道一条密道",
                "隐藏了真实的身份", "在寻找失散的家人"
            ]),
        }

    @classmethod
    def encounter(cls, env: str = "wilderness") -> str:
        """随机遭遇。"""
        tables = {
            "urban": cls.URBAN_ENCOUNTERS,
            "wilderness": cls.WILDERNESS_ENCOUNTERS,
            "dungeon": cls.DUNGEON_ENCOUNTERS,
        }
        return random.choice(tables.get(env, cls.WILDERNESS_ENCOUNTERS))

    @classmethod
    def loot(cls, quality: str = "common") -> str:
        """随机战利品。"""
        return random.choice(cls.LOOT_TABLES.get(quality, cls.LOOT_TABLES["common"]))

    @classmethod
    def weather(cls, climate: str = "temperate") -> str:
        """随机天气。"""
        return random.choice(cls.WEATHER_TABLES.get(climate, cls.WEATHER_TABLES["temperate"]))

    @classmethod
    def treasure_hoard(cls, level: int = 1) -> Dict[str, Any]:
        """随机宝藏堆。"""
        qualities = ["poor", "common", "uncommon", "rare", "legendary"]
        idx = min(max(level - 1, 0), len(qualities) - 1)
        quality = qualities[idx]
        count = random.randint(1, 4)
        items = [cls.loot(quality) for _ in range(count)]
        return {
            "quality": quality,
            "items": items,
            "gold": random.randint(10 * level, 100 * level),
        }


# ============================================================
# 3. 程序化内容生成
# ============================================================
class ProceduralGen:
    """程序化内容生成器。"""

    # ---- 地名组件 ----
    PLACE_PREFIXES = ["古老", "隐秘", "失落", "光辉", "暗影", "雷鸣", "翡翠", "铁铸",
                       "龙眠", "星辰", "深渊", "苍翠", "赤红", "银白", "幽暗"]
    PLACE_TYPES = ["神殿", "要塞", "森林", "沼泽", "山峰", "峡谷", "遗迹", "洞穴",
                   "港口", "村庄", "学院", "塔楼", "矿坑", "圣所", "墓地"]
    PLACE_SUFFIXES = ["之谷", "之巅", "废墟", "深处", "边境", "走廊", "秘境", "海岸"]

    # ---- 任务生成 ----
    QUEST_TEMPLATES = [
        ("{npc}请求你前往{place}寻找{object}", "寻物"),
        ("{place}的{npc}需要保护，{enemy}正在逼近", "护卫"),
        ("调查{place}中离奇失踪的{npc}", "调查"),
        ("击败盘踞在{place}的{enemy}", "讨伐"),
        ("护送{npc}安全抵达{place}", "护送"),
        ("从{place}的{enemy}手中救出{npc}", "营救"),
        ("收集{count}个{object}交给{npc}", "采集"),
        ("破解{place}中的古老谜题", "解谜"),
    ]

    # ---- 宝物描述 ----
    MAGIC_PREFIXES = ["燃烧", "冰冻", "暗影", "神圣", "闪电", "剧毒", "回音", "虚空",
                       "幻影", "不朽", "龙息", "月光", "血怒", "星陨", "潮汐"]
    MAGIC_TYPES = ["长剑", "法杖", "护符", "戒指", "斗篷", "盾牌", "弓", "匕首",
                   "战锤", "权杖", "头冠", "臂铠", "吊坠", "典籍", "号角"]

    ENEMY_PREFIXES = ["巨型", "暗影", "腐化", "远古", "烈焰", "冰霜", "毒液", "幻影",
                       "钢铁", "狂野", "亡灵", "恶魔", "元素", "深渊", "扭曲"]
    ENEMY_TYPES = ["狼", "蜘蛛", "蛇", "石像鬼", "魔像", "巨龙", "骑士", "巫师",
                   "巨人", "幽灵", "吸血鬼", "树精", "鹰身女妖", "食人魔", "甲虫"]

    @classmethod
    def place_name(cls) -> str:
        """随机地点名。"""
        chance = random.random()
        if chance < 0.4:
            return f"{random.choice(cls.PLACE_PREFIXES)}{random.choice(cls.PLACE_TYPES)}"
        elif chance < 0.8:
            return f"{random.choice(cls.PLACE_PREFIXES)}{random.choice(cls.PLACE_TYPES)}{random.choice(cls.PLACE_SUFFIXES)}"
        else:
            return f"{random.choice(cls.PLACE_TYPES)}{random.choice(cls.PLACE_SUFFIXES)}"

    @classmethod
    def magic_item(cls) -> Dict[str, str]:
        """随机魔法物品。"""
        return {
            "name": f"{random.choice(cls.MAGIC_PREFIXES)}之{random.choice(cls.MAGIC_TYPES)}",
            "bonus": f"+{random.randint(1, 3)}",
            "special": random.choice([
                "对亡灵额外伤害", "击中回复生命", "释放火焰冲击",
                "免疫恐惧", "水下呼吸", "黑暗视觉 60ft",
                "一天一次隐形术", "周围10尺照亮",
            ]),
        }

    @classmethod
    def enemy(cls) -> Dict[str, str]:
        """随机敌人。"""
        return {
            "name": f"{random.choice(cls.ENEMY_PREFIXES)}{random.choice(cls.ENEMY_TYPES)}",
            "cr": str(random.randint(1, 8)),
            "tactic": random.choice([
                "伏击", "正面冲锋", "远程骚扰", "召唤援军", "逃跑拖延"
            ]),
        }

    @classmethod
    def quest(cls) -> Dict[str, str]:
        """随机任务。"""
        template, qtype = random.choice(cls.QUEST_TEMPLATES)
        npc = RandomTables.npc_name()
        place = cls.place_name()
        enemy = cls.enemy()["name"]
        obj = random.choice(["魔法水晶", "古老卷轴", "遗失的钥匙", "封印之书", "国王密令"])
        count = str(random.randint(3, 10))

        text = template.format(npc=npc, place=place, enemy=enemy, object=obj, count=count)
        return {"title": text, "type": qtype, "location": place, "reward": RandomTables.loot("common")}

    @classmethod
    def tavern_name(cls) -> str:
        """随机酒馆名。"""
        a = random.choice(["跳跃", "沉睡", "微笑", "咆哮", "红", "金", "黑", "白", "蓝", "绿"])
        b = random.choice(["巨龙", "独角兽", "水手", "吟游诗人", "渡鸦", "狐狸", "熊", "美人鱼", "矮人", "精灵"])
        return f"「{a}{b}」旅店"


# ============================================================
# 4. 战报日记
# ============================================================
@dataclass
class CampaignEntry:
    """单条战报记录。"""
    timestamp: str
    turn: int
    event_type: str  # "scene" / "combat" / "chat" / "system"
    description: str
    details: Dict[str, Any] = field(default_factory=dict)


class CampaignJournal:
    """战报日记：记录每一轮游戏事件，支持导出和回顾。

    参考 Archivist 的 session recap 模式。
    """

    def __init__(self, campaign_name: str = "未命名战役"):
        self.campaign_name = campaign_name
        self.entries: List[CampaignEntry] = []
        self.turn_counter: int = 0
        self.started_at: str = datetime.now().isoformat()

    def log_scene(self, node_id: str, narrative: str, dice_result: Dict = None):
        self.turn_counter += 1
        self.entries.append(CampaignEntry(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            turn=self.turn_counter,
            event_type="scene",
            description=f"[{node_id}] {narrative[:100]}",
            details={"node_id": node_id, "dice": dice_result or {}},
        ))

    def log_combat(self, enemy_name: str, action: str, result: str):
        self.turn_counter += 1
        self.entries.append(CampaignEntry(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            turn=self.turn_counter,
            event_type="combat",
            description=f"⚔ [{enemy_name}] {action}: {result}",
            details={"enemy": enemy_name, "action": action},
        ))

    def log_chat(self, user_input: str, ai_reply: str):
        self.turn_counter += 1
        self.entries.append(CampaignEntry(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            turn=self.turn_counter,
            event_type="chat",
            description=f"玩家: {user_input[:60]}",
            details={"user": user_input, "ai": ai_reply},
        ))

    def log_system(self, message: str):
        self.entries.append(CampaignEntry(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            turn=self.turn_counter,
            event_type="system",
            description=message,
        ))

    def generate_recap(self, last_n: int = 10) -> str:
        """生成最近 N 条事件的回顾摘要。"""
        recent = self.entries[-last_n:]
        if not recent:
            return "暂无记录。"
        lines = [f"【{self.campaign_name} 战报回顾】"]
        for e in recent:
            icon = {"scene": "📖", "combat": "⚔", "chat": "💬", "system": "⚙"}.get(e.event_type, "")
            lines.append(f"  #{e.turn} {icon} {e.description}")
        return "\n".join(lines)

    def export(self, filepath: str):
        """导出为 JSON。"""
        data = {
            "campaign": self.campaign_name,
            "started_at": self.started_at,
            "exported_at": datetime.now().isoformat(),
            "total_turns": self.turn_counter,
            "entries": [
                {
                    "turn": e.turn,
                    "time": e.timestamp,
                    "type": e.event_type,
                    "description": e.description,
                    "details": e.details,
                }
                for e in self.entries
            ],
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @property
    def summary(self) -> Dict[str, Any]:
        etypes = {}
        for e in self.entries:
            etypes[e.event_type] = etypes.get(e.event_type, 0) + 1
        return {
            "campaign": self.campaign_name,
            "total_turns": self.turn_counter,
            "entries": len(self.entries),
            "by_type": etypes,
        }

    def __repr__(self):
        s = self.summary
        return f"<CampaignJournal '{self.campaign_name}' turns={s['total_turns']} entries={s['entries']}>"


# ============================================================
# 便捷函数
# ============================================================
def roll(notation: str) -> Tuple[int, List[int], str]:
    """快捷掷骰: roll("3d6+2")"""
    return DiceRoller.roll(notation)


def random_npc() -> Dict[str, str]:
    """快捷 NPC 生成。"""
    return RandomTables.npc_full()


def random_quest() -> Dict[str, str]:
    """快捷任务生成。"""
    return ProceduralGen.quest()


def random_loot(quality: str = "common") -> str:
    """快捷战利品。"""
    return RandomTables.loot(quality)
