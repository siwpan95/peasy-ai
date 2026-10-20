"""
AI 训练器：将 TRPG 游戏事件转换为 AICore 的学习数据。

核心思想：跑团不是独立系统，而是 AI 的训练场。
每场检定、每场战斗、每段叙事——都是 AI 的"教材"。

AICore 是大脑，paotuan 引擎提供结构化的训练场景。
"""

import sys
import os
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

# 命名空间包：导入由 easy_ai 包自身保证，无需 sys.path 自举

from easy_ai.ai.core import AICore


@dataclass
class TrainingRecord:
    """一条训练记录。"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    source: str = ""          # "scene" / "combat" / "character" / "rule" / "manual"
    question: str = ""         # AI 被教的问题
    answer: str = ""           # AI 学到的答案
    context: Dict = field(default_factory=dict)  # 附加上下文


class AITrainer:
    """
    AI 训练器：桥接 paotuan 游戏事件 → AICore 知识学习。

    用法：
        trainer = AITrainer(ai_core)
        trainer.on_scene_result(scene_id, skill, roll, target, success, narrative)
        trainer.on_combat_event(enemy_name, action, damage, result)
        trainer.on_character_load(character_data)
        trainer.export_training_log("training.json")
    """

    def __init__(self, ai: AICore):
        self.ai = ai
        self.records: List[TrainingRecord] = []
        self.trained_count: int = 0

    # ============================================================
    # 事件 → 学习
    # ============================================================

    def on_scene_result(self, node_id: str, skill_used: str,
                        roll: int, target: int, success: bool,
                        narrative: str):
        """场景检定完成 → AI 学习。"""
        # 学习 1: 检定结果
        result_word = "成功" if success else "失败"
        q1 = f"{skill_used}检定是什么结果"
        a1 = f"{result_word}：掷出{roll}，目标{target}，差值{abs(target-roll)}。"
        self._learn(q1, a1, "scene", {"node": node_id, "skill": skill_used})

        # 学习 2: 场景叙事
        if narrative and len(narrative) > 5:
            q2 = f"在{node_id}场景中发生了什么"
            a2 = narrative
            self._learn(q2, a2, "scene", {"node": node_id})

        # 学习 3: 技能知识
        q3 = f"{skill_used}技能有什么用"
        a3 = f"{skill_used}用于{node_id}场景的检定，目标值{target}。"
        self._learn(q3, a3, "scene", {"skill": skill_used})

    def on_combat_event(self, enemy_name: str, enemy_hp: int,
                        action: str, damage: int, hit_location: str = "",
                        killed: bool = False):
        """战斗事件 → AI 学习。"""
        # 学习敌人信息
        q1 = f"{enemy_name}是什么"
        a1 = f"{enemy_name}，HP{enemy_hp}。战斗中的敌人。"
        self._learn(q1, a1, "combat", {"enemy": enemy_name})

        # 学习战斗结果
        if hit_location:
            q2 = f"攻击{enemy_name}的{hit_location}造成了多少伤害"
            a2 = f"造成了{damage}点伤害。" + ("成功击杀。" if killed else "")
            self._learn(q2, a2, "combat", {"enemy": enemy_name, "action": action})

        # 学习战术
        q3 = f"如何对付{enemy_name}"
        a3 = f"使用{action}战术，造成了{damage}点伤害。" + (
            "已成功消灭。" if killed else "它仍在战斗中。")
        self._learn(q3, a3, "combat", {"enemy": enemy_name})

    def on_character_load(self, character: Dict):
        """角色加载 → AI 学习。"""
        name = character.get("name", "未知")
        st = character.get("st", 10)
        dx = character.get("dx", 10)
        iq = character.get("iq", 10)
        ht = character.get("ht", 10)

        q = f"{name}的属性是什么"
        a = f"ST{st}(力量) DX{dx}(敏捷) IQ{iq}(智力) HT{ht}(体质)。"
        self._learn(q, a, "character", {"name": name})

        # 学习技能
        for skill in character.get("skills", []):
            sk = f"{name}的{skill.get('name','?')}技能等级是多少"
            sa = f"等级{skill.get('level','?')}（{skill.get('difficulty','?')}难度）。"
            self._learn(sk, sa, "character", {"name": name})

        # 学习装备
        for eq in character.get("equipment", []):
            ek = f"{name}装备了{str(eq)}吗"
            self._learn(ek, f"是的装备了{str(eq)}。", "character", {"name": name})

    def on_rule_query(self, rule_topic: str, explanation: str):
        """规则查询 → AI 学习。"""
        q = f"{rule_topic}的规则是什么"
        self._learn(q, explanation, "rule", {"topic": rule_topic})

    def on_manual_teach(self, question: str, answer: str):
        """手动教学。"""
        self._learn(question, answer, "manual", {})

    # ============================================================
    # 内部
    # ============================================================

    def _learn(self, question: str, answer: str, source: str,
               context: Dict):
        """喂给 AI 并记录。"""
        if self.ai.learn(question, answer):
            self.trained_count += 1
            self.records.append(TrainingRecord(
                source=source, question=question,
                answer=answer, context=context,
            ))

    # ============================================================
    # 导出
    # ============================================================

    def export_training_log(self, filepath: str):
        """导出训练日志为 JSON。"""
        import json
        data = {
            "trained_at": datetime.now().isoformat(),
            "total_learned": self.trained_count,
            "records": [
                {
                    "time": r.timestamp,
                    "source": r.source,
                    "question": r.question,
                    "answer": r.answer,
                    "context": r.context,
                }
                for r in self.records
            ],
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ============================================================
    # 信息
    # ============================================================

    @property
    def summary(self) -> Dict[str, Any]:
        sources = {}
        for r in self.records:
            sources[r.source] = sources.get(r.source, 0) + 1
        return {
            "total": self.trained_count,
            "by_source": sources,
            "ai_memory": self.ai.memory_count,
            "ai_answers": self.ai.memory.total_answers,
        }

    def __repr__(self):
        s = self.summary
        return (f"<AITrainer learned={s['total']} "
                f"memory={s['ai_memory']}>")
