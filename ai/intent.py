"""
意图识别器：从用户输入中提取关键词并分类意图。

特性：
- 关键词提取（基于词频 + 配置化的 stopwords）
- 简单意图分类（greeting / question / command / statement / farewell）
- 规则 + ML 混合模式（ML 需要 scikit-learn 可选依赖）
"""

import re
from typing import Dict, List, Any, Optional, Tuple
from collections import Counter


class IntentClassifier:
    """基于规则 + 可选 ML 的意图分类器。"""

    # 默认 stopwords
    DEFAULT_STOPWORDS = {
        '的', '了', '是', '在', '我', '你', '他', '她', '它',
        '和', '与', '或', '不', '都', '很', '也', '就', '要',
        '会', '能', '有', '对', '这', '那', '个', '吗', '吧',
        '呢', '啊', '哦', '嗯', '么', '什么', '怎么', '为什么',
    }

    # 规则型意图模式
    INTENT_RULES = {
        "greeting": [r'^(你好|嗨|hello|hi|哈喽|早上好|下午好|晚上好)'],
        "farewell": [r'^(再见|拜拜|bye|回头见|下次见|晚安)'],
        "question": [r'(什么|怎么|为什么|多少|哪里|哪个|谁|吗\?|呢\?)'],
        "command": [r'^(帮我|给我|查找|搜索|打开|关闭|设置|请)'],
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.stopwords = set(self.config.get("stopwords", [])) | self.DEFAULT_STOPWORDS
        self.min_keyword_len = self.config.get("min_keyword_len", 2)

    def extract_keywords(self, text: str, top_n: int = 5) -> List[Tuple[str, float]]:
        """提取关键词及权重。

        Returns:
            [(keyword, weight), ...] 按权重降序。
        """
        # 分词（简单按字符/词切分）
        words = re.findall(r'[\u4e00-\u9fa5]+|[a-zA-Z]+', text)

        # 过滤停用词和短词
        filtered = [w for w in words
                    if w not in self.stopwords and len(w) >= self.min_keyword_len]

        # 词频统计
        counter = Counter(filtered)
        total = sum(counter.values()) or 1

        # 归一化权重
        keywords = [(word, count / total) for word, count in counter.most_common(top_n)]
        return keywords

    def classify(self, text: str) -> Tuple[str, float]:
        """分类意图。

        Returns:
            (intent_label, confidence)
            intent_label: greeting/farewell/question/command/statement
        """
        text_lower = text.strip().lower()

        # 规则匹配
        for intent, patterns in self.INTENT_RULES.items():
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    return intent, 0.8

        # 简单启发式
        if text.endswith('?') or text.endswith('？'):
            return "question", 0.7
        if len(text) < 4:
            return "statement", 0.5

        return "statement", 0.3

    def is_question(self, text: str) -> bool:
        intent, _ = self.classify(text)
        return intent == "question"

    def is_greeting(self, text: str) -> bool:
        intent, _ = self.classify(text)
        return intent == "greeting"

    def is_farewell(self, text: str) -> bool:
        intent, _ = self.classify(text)
        return intent == "farewell"
