"""
条件求值器：递归解析嵌套的 and/or 逻辑。

支持的条件类型（全部由 JSON 数据定义，代码零硬编码）：
- {"attr": "religion", "min": 20}     → 属性 >= 20
- {"attr": "people", "max": 80}       → 属性 <= 80
- {"has_clue": "letter"}              → 已收集线索
- {"flag": "chose_tax"}               → 标记已设置
- {"and": [cond1, cond2, ...]}        → 全部为真
- {"or": [cond1, cond2, ...]}         → 任一为真
- {"not": cond}                        → 取反
"""

from typing import Dict, Any, Optional

from .models import GameState


class ConditionEvaluator:
    """根据 GameState 计算条件是否为真。"""

    def check(self, condition: Optional[Dict[str, Any]], state: GameState) -> bool:
        """
        递归求值一个条件对象。

        Args:
            condition: JSON 条件对象，None 视为无条件通过。
            state: 当前游戏状态。

        Returns:
            True 表示条件满足。
        """
        if not condition:
            return True

        # ---- 复合条件 ----
        if "and" in condition:
            return all(self.check(sub, state) for sub in condition["and"])

        if "or" in condition:
            return any(self.check(sub, state) for sub in condition["or"])

        if "not" in condition:
            return not self.check(condition["not"], state)

        # ---- 原子条件 ----
        # 属性范围检查
        if "attr" in condition:
            attr_name = condition["attr"]
            current = state.attributes.get(attr_name, 0)
            if "min" in condition and current < condition["min"]:
                return False
            if "max" in condition and current > condition["max"]:
                return False
            if "eq" in condition and current != condition["eq"]:
                return False
            return True

        # 线索检查
        if "has_clue" in condition:
            return condition["has_clue"] in state.clues

        # 标记检查
        if "has_flag" in condition:
            return condition["has_flag"] in state.flags

        # 旧 API 兼容：flag
        if "flag" in condition:
            return condition["flag"] in state.flags

        # 未知条件 → 默认通过（允许扩展）
        return True
