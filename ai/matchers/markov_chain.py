"""
马尔科夫链文本生成器：基于 n-gram 的概率语言模型。

特性：
- N-gram 训练（支持 1-5 gram）
- 带温度控制的随机采样
- 权重衰减（长匹配 > 短匹配）
- 可作为匹配器集成到 Pipeline
- 纯 Python 标准库实现，零外部依赖

参考：马尔科夫链在 NLP 中的经典应用：给定当前状态（前 n-1 个 token），
通过概率分布预测下一个 token。这是统计语言模型的基石。
"""

import random
import re
from collections import defaultdict
from typing import Dict, List, Optional, Any, Tuple, Set

from .base import BaseMatcher, MatchResult
from .registry import register_matcher


class MarkovChain:
    """N-gram 马尔科夫链文本模型。

    原理：
    1. 训练阶段：扫描语料，构建 (prefix) -> [next_token1, next_token2, ...] 的转移表
    2. 生成阶段：给定起始 prefix，按转移概率采样下一个 token，滑动窗口继续
    3. 回退策略：当 n-gram 未命中时，自动降级到 (n-1)-gram
    """

    def __init__(self, n: int = 2):
        """
        Args:
            n: n-gram 的 n，默认 2（bigram）。推荐 2-4。
        """
        if n < 1:
            raise ValueError(f"n 必须 >= 1，当前值：{n}")
        self.n = max(1, n)
        self._chains: Dict[int, Dict[Tuple[str, ...], List[str]]] = {}
        self._token_vocab: Set[str] = set()
        self._trained = False

    def train(self, texts: List[str], tokenize: bool = True):
        """用文本列表训练马尔科夫链。

        Args:
            texts: 训练文本列表
            tokenize: 是否按字符/词分割。True 按字符切分（适合中文），
                     提供 jieba 时可改为按词切分。
        """
        all_tokens: List[List[str]] = []
        for text in texts:
            if not text or not text.strip():
                continue
            if tokenize:
                tokens = self._tokenize(text)
            else:
                tokens = text.split()
            if len(tokens) < self.n:
                continue
            all_tokens.append(tokens)

        if not all_tokens:
            return

        self._chains.clear()
        self._token_vocab.clear()

        # 对每个 n-gram 级别（从 n 到 1）构建回退链
        for level in range(self.n, 0, -1):
            chain: Dict[Tuple[str, ...], List[str]] = defaultdict(list)
            for tokens in all_tokens:
                for i in range(len(tokens) - level):
                    prefix = tuple(tokens[i:i + level])
                    next_token = tokens[i + level]
                    chain[prefix].append(next_token)
                    self._token_vocab.add(next_token)
                # 收集所有 token
                for t in tokens:
                    self._token_vocab.add(t)
            self._chains[level] = chain

        self._trained = True

    def _tokenize(self, text: str) -> List[str]:
        """智能分词：中文字符分割 + 英文单词保持。

        用正则同时匹配中文字符和英文单词/数字。
        """
        tokens = re.findall(r'[\u4e00-\u9fff]|[a-zA-Z]+|\d+|[^\s]', text)
        # 过滤纯空白
        return [t for t in tokens if t.strip()]

    def sample(self, start: Optional[str] = None, max_length: int = 50,
               temperature: float = 1.0, seed_prefix: Optional[List[str]] = None) -> str:
        """从马尔科夫链采样生成文本。

        Args:
            start: 起始词（可选）。为 None 时随机选择。
            max_length: 最大生成长度（token 数）
            temperature: 温度参数。0=确定性，1=正常，>1=更随机
            seed_prefix: 自定义起始 token 列表（优先级高于 start）

        Returns:
            生成的文本
        """
        if not self._trained:
            return ""

        primary_chain = self._chains.get(self.n, {})
        if not primary_chain:
            return ""

        # 确定起始 prefix
        if seed_prefix and len(seed_prefix) >= self.n:
            current = tuple(seed_prefix[-self.n:])
        elif start:
            start_tokens = self._tokenize(start)
            if len(start_tokens) >= self.n:
                current = tuple(start_tokens[-self.n:])
            else:
                # 补全到 n 个
                current = tuple(start_tokens)
        else:
            current = random.choice(list(primary_chain.keys()))

        generated = list(current)

        for _ in range(max_length):
            next_token = self._predict(current, temperature)
            if next_token is None:
                break
            generated.append(next_token)

            # 滑动窗口：去掉最老的 token，加入新 token
            if len(current) >= self.n:
                current = current[1:] + (next_token,)
            else:
                current = current + (next_token,)

            # 自然终止检测（遇到句号、问号、感叹号后有一定概率停止）
            if next_token in ('。', '！', '？', '!', '?', '.') and random.random() < 0.3:
                break

        return ''.join(generated)

    def _predict(self, prefix: Tuple[str, ...], temperature: float = 1.0) -> Optional[str]:
        """根据 prefix 预测下一个 token（带回退）。

        回退策略：当前 n-gram 未命中时，尝试 (n-1)-gram，直到 1-gram 兜底。
        """
        # 从最高阶 n-gram 开始尝试
        for level in range(self.n, 0, -1):
            chain = self._chains.get(level, {})
            if not chain:
                continue

            # 截取 prefix 的最后 level 个元素
            key = prefix[-level:] if len(prefix) >= level else prefix
            candidates = chain.get(key, [])
            if candidates:
                return self._weighted_sample(candidates, temperature)

        return None

    def _weighted_sample(self, candidates: List[str], temperature: float = 1.0) -> str:
        """带温度的加权采样。

        temperature=0: 返回最高频的 token
        temperature=1: 按频率比例采样
        temperature>1: 平滑分布，更随机
        """
        if temperature <= 0:
            return max(set(candidates), key=candidates.count)

        # 统计频率
        freq: Dict[str, int] = defaultdict(int)
        for token in candidates:
            freq[token] += 1

        tokens = list(freq.keys())
        counts = [freq[t] for t in tokens]

        # 温度缩放
        if temperature != 1.0:
            scaled = [c ** (1.0 / temperature) for c in counts]
        else:
            scaled = counts

        total = sum(scaled)
        r = random.random() * total
        cumulative = 0.0
        for token, weight in zip(tokens, scaled):
            cumulative += weight
            if r <= cumulative:
                return token

        return tokens[-1]

    def generate_variations(self, seed: str, count: int = 5,
                            temperature: float = 0.8, max_length: int = 60) -> List[str]:
        """生成多个变体文本（用于对话回复多样性）。"""
        variations = []
        seen = set()
        for _ in range(count * 3):  # 多试几次去重
            text = self.sample(start=seed, max_length=max_length, temperature=temperature)
            if text and text not in seen:
                seen.add(text)
                variations.append(text)
            if len(variations) >= count:
                break
        return variations

    def get_transition_probability(self, prefix: Tuple[str, ...], next_token: str) -> float:
        """计算给定 prefix 下 next_token 的转移概率。"""
        chain = self._chains.get(self.n, {})
        candidates = chain.get(prefix, [])
        if not candidates:
            return 0.0
        return candidates.count(next_token) / len(candidates)

    @property
    def vocab_size(self) -> int:
        return len(self._token_vocab)

    @property
    def total_states(self) -> int:
        return sum(len(c) for c in self._chains.values())

    @property
    def is_trained(self) -> bool:
        return self._trained

    def __repr__(self):
        return (f"<MarkovChain n={self.n} vocab={self.vocab_size} "
                f"states={self.total_states} trained={self._trained}>")


@register_matcher("markov")
class MarkovMatcher(BaseMatcher):
    """马尔科夫链匹配器：集成到 easy-ai Pipeline 中。

    与传统匹配器不同，马尔科夫匹配器不是"匹配到固定回复"，
    而是"基于已有语料概率生成回复"——更具创造性和多样性。

    优先级设为 30（低于 Regex/10 和 Fuzzy/20），作为创意兜底。
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "MarkovMatcher"
        cfg = config or {}
        self.priority = cfg.get("priority", 30)
        self.n_gram = cfg.get("n_gram", 3)
        self.temperature = cfg.get("temperature", 0.8)
        self.max_length = cfg.get("max_length", 80)
        self._model = MarkovChain(n=self.n_gram)
        self._corpus_keywords: Dict[str, List[Tuple[str, ...]]] = {}  # 关键词 -> 起始 n-gram 列表

    def build_from_rules(self, rules: List[Dict[str, Any]]):
        """从规则库构建马尔科夫链语料。

        将每个规则的 pattern（用户可能说的话）和 responses（AI 回复）
        分别作为用户语料和 AI 语料进行训练。
        """
        user_texts: List[str] = []
        ai_texts: List[str] = []

        for rule in rules:
            pattern = rule.get("pattern", "")
            responses = rule.get("responses", [])

            # 收集模式变体（从 pattern 提取多个版本）
            if pattern and pattern != ".*":
                user_texts.append(self._clean_pattern(pattern))

            # 收集回复作为 AI 语料
            for resp in responses:
                ai_texts.append(resp)

        # 合并训练
        all_texts = user_texts + ai_texts
        if all_texts:
            self._model.train(all_texts)

        # 构建关键词索引
        self._build_keyword_index(rules)

    def build_from_texts(self, texts: List[str]):
        """直接用文本列表训练。"""
        self._model.train(texts)
        self._build_corpus_keywords(texts)

    def _clean_pattern(self, pattern: str) -> str:
        """清洗正则 pattern 为可读文本。"""
        # 移除正则特殊字符
        cleaned = re.sub(r'[.*+?^$(){}|\[\]\\]', '', pattern)
        return cleaned.strip()

    def _build_keyword_index(self, rules: List[Dict[str, Any]]):
        """为语料构建关键词索引，支持快速检索相关起始 n-gram。"""
        self._corpus_keywords.clear()

    def _build_corpus_keywords(self, texts: List[str]):
        """从文本列表提取关键词索引。"""
        self._corpus_keywords.clear()
        chain = self._model._chains.get(self._model.n, {})
        for prefix in chain:
            prefix_text = ''.join(prefix)
            for text in texts:
                if prefix_text in text:
                    key = text[:10]  # 用前 10 个字符作为关键词
                    if key not in self._corpus_keywords:
                        self._corpus_keywords[key] = []
                    self._corpus_keywords[key].append(prefix)

    def match(self, text: str, rules: List[Dict[str, Any]]) -> Optional[MatchResult]:
        """基于马尔科夫链生成回复。

        策略：
        1. 用用户输入作为 seed
        2. 生成多个候选回复
        3. 选最优的返回
        """
        if not self._model.is_trained:
            self.build_from_rules(rules)

        if not self._model.is_trained:
            return None

        # 用用户输入作为 seed 生成
        generated = self._model.sample(
            start=text,
            max_length=self.max_length,
            temperature=self.temperature
        )

        if not generated or len(generated) < 2:
            return None

        # 置信度 = 生成文本与原文本的重叠度
        confidence = self._calculate_overlap(text, generated)

        return MatchResult(
            reply=generated,
            confidence=min(confidence, 0.75),  # 上限 0.75（低于精确匹配）
            source=self.name,
            metadata={"n_gram": self.n_gram, "temperature": self.temperature}
        )

    def _calculate_overlap(self, a: str, b: str) -> float:
        """计算两个文本的字符级重叠度。"""
        if not a or not b:
            return 0.0
        set_a = set(a)
        set_b = set(b)
        if not set_a:
            return 0.0
        intersection = set_a & set_b
        return len(intersection) / len(set_a | set_b) * 0.5 + 0.25  # 基础置信度

    def generate(self, seed: str, count: int = 3, temperature: float = None) -> List[str]:
        """生成多个候选回复（供外部调用）。"""
        if not self._model.is_trained:
            return []
        temp = temperature or self.temperature
        return self._model.generate_variations(seed, count=count, temperature=temp)

    @property
    def model(self) -> MarkovChain:
        return self._model

    def __repr__(self):
        return (f"<MarkovMatcher n={self.n_gram} "
                f"priority={self.priority} trained={self._model.is_trained}>")
