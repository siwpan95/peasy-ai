"""
数学计算响应器：自动计算数学表达式并返回结果。

支持中文口语表达（"四加五等于几""一百除以五"等）。
安全：只执行安全的 eval，使用受限的全局/局部命名空间。
"""

import re
import random
from typing import Optional, Dict, Any

from .registry import register_responder

# 中文数字 → 阿拉伯数字
CN_NUM = {
    '零': '0', '一': '1', '二': '2', '三': '3', '四': '4',
    '五': '5', '六': '6', '七': '7', '八': '8', '九': '9',
    '十': '10', '两': '2',
}

# 中文运算符 → 符号
CN_OPS = {
    '加': '+', '加上': '+', '减': '-', '减去': '-',
    '乘': '*', '乘以': '*', '除': '/', '除以': '/',
    '等于': '=', '等于几': '=?', '是多少': '=?',
}


@register_responder("math")
class MathResponder:
    """自动识别并计算数学表达式。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)

        self.templates = self.config.get("templates", [
            "计算结果是：{result}。",
            "{expression} = {result}。",
            "答案是 {result}。",
        ])

        # 安全命名空间
        import math
        self._safe_globals = {
            "__builtins__": {
                "abs": abs, "round": round, "min": min, "max": max,
                "sum": sum, "pow": pow, "int": int, "float": float,
            },
            "math": math,
        }

    def process(self, text: str) -> Optional[str]:
        # 方法 1: 中文口语表达式
        result = self._try_cn_math(text)
        if result is not None:
            return result

        # 方法 2: 纯数字表达式（如 "1+2*3"）
        result = self._try_raw_math(text)
        return result

    def _try_cn_math(self, text: str) -> Optional[str]:
        """解析"四加五等于几"这类中文表达式。"""
        # 替换中文数字
        converted = text
        for cn, num in sorted(CN_NUM.items(), key=lambda x: -len(x[0])):
            converted = converted.replace(cn, num)

        # 替换中文运算符
        for cn_op, symbol in sorted(CN_OPS.items(), key=lambda x: -len(x[0])):
            converted = converted.replace(cn_op, symbol)

        # 提取可能的数学表达式
        expr_match = re.search(r'([\d\s+\-*/().]+)\s*=\s*\??', converted)
        if not expr_match:
            # 尝试无等号形式："四加五"
            expr_match = re.search(r'([\d]+)\s*([+\-*/])\s*([\d]+)', converted)

        if not expr_match:
            return None

        expression = expr_match.group(0).rstrip('=? ').strip()
        if not expression or not re.search(r'[\d]', expression):
            return None

        try:
            result = eval(expression, self._safe_globals, {})
            return random.choice(self.templates).format(
                result=self._format_result(result),
                expression=expression
            )
        except Exception:
            return None

    def _try_raw_math(self, text: str) -> Optional[str]:
        """解析纯数学表达式如 "1+2", "3*4/2"。"""
        # 只匹配包含运算符的表达式
        expr_match = re.search(r'([\d]+\s*[+\-*/]\s*[\d\s+\-*/().]+)', text)
        if not expr_match:
            return None

        expression = expr_match.group(1).strip()
        # 安全检查：只允许数字和基本运算符
        if not re.match(r'^[\d\s+\-*/().]+$', expression):
            return None

        try:
            result = eval(expression, self._safe_globals, {})
            return random.choice(self.templates).format(
                result=self._format_result(result),
                expression=expression
            )
        except Exception:
            return None

    def _format_result(self, value) -> str:
        """格式化结果：整型去小数点。"""
        if isinstance(value, float) and value == int(value):
            return str(int(value))
        return str(value)
