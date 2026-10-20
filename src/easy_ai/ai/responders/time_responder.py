"""
时间查询响应器：回答"几点了""今天星期几""今天几号"等问题。

零外部依赖，纯 Python datetime + 正则匹配。
"""

import re
import random
from datetime import datetime
from typing import Optional, Dict, Any

from .registry import register_responder


@register_responder("time")
class TimeResponder:
    """回答时间相关问题。"""

    # 匹配模式
    TIME_PATTERNS = [
        (r'(现在|当前).*(几点|时间|几时)', 'time'),
        (r'(几点了|现在几点|什么时间)', 'time'),
        (r'(今天|当前).*(星期|周几|礼拜)', 'weekday'),
        (r'(今天|当前).*(几号|日期|什么日子)', 'date'),
    ]

    # 中文字星期
    WEEKDAY_CN = ['一', '二', '三', '四', '五', '六', '日']

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)

        # 可自定义回复模板
        self.time_templates = self.config.get("time_templates", [
            "现在是 {time}。",
            "当前时间：{time}。",
            "已经 {time} 啦！",
        ])
        self.date_templates = self.config.get("date_templates", [
            "今天是 {date}。",
            "今天是 {year}年{month}月{day}日。",
        ])
        self.weekday_templates = self.config.get("weekday_templates", [
            "今天是星期{weekday}。",
            "今天周{weekday}。",
        ])

    def process(self, text: str) -> Optional[str]:
        """对时间相关问题返回答案，否则返回 None。"""
        for pattern, qtype in self.TIME_PATTERNS:
            if re.search(pattern, text):
                return self._answer(qtype)
        return None

    def _answer(self, qtype: str) -> str:
        now = datetime.now()
        if qtype == 'time':
            return random.choice(self.time_templates).format(
                time=now.strftime("%H:%M:%S")
            )
        elif qtype == 'date':
            return random.choice(self.date_templates).format(
                date=now.strftime("%Y-%m-%d"),
                year=now.year, month=now.month, day=now.day
            )
        elif qtype == 'weekday':
            return random.choice(self.weekday_templates).format(
                weekday=self.WEEKDAY_CN[now.weekday()]
            )
        return None
