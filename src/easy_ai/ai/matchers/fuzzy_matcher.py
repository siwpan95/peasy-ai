"""
模糊语义匹配器：基于文本相似度的模糊匹配。

策略：
1. TF-IDF + 余弦相似度（需 scikit-learn + jieba）
2. 字符 N-Gram Jaccard 相似度（纯 Python，优于编辑距离）
3. 编辑距离降级（纯 Python，最终兜底）

返回 MatchResult，confidence = similarity_score。
"""

import re
import random
from typing import Dict, List, Any, Optional, Set
from collections import Counter

from .base import BaseMatcher, MatchResult
from .registry import register_matcher


@register_matcher("fuzzy")
class FuzzyMatcher(BaseMatcher):
    """基于文本相似度的模糊匹配器。

    增强特性：
    - 字符 N-Gram Jaccard 相似度：对中文更友好，捕捉局部共现
    - 关键词加权匹配：提取实义词提高匹配质量
    - 多策略衰减：TF-IDF > N-Gram > 编辑距离
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "FuzzyMatcher"
        cfg = config or {}
        self.priority = cfg.get("priority", 20)
        self.threshold = cfg.get("threshold", 0.3)
        self.min_confidence = cfg.get("min_confidence", self.threshold)
        self._ngram_n = cfg.get("ngram_n", 3)  # 字符 n-gram 的 n
        self._use_tfidf = False

        self._vectorizer = None
        self._matrix = None
        self._corpus_answers: List[str] = []

        if cfg.get("use_tfidf", True):
            self._try_load_tfidf()

    def _try_load_tfidf(self):
        """探测可选依赖（TF-IDF 增强路径）。

        ⚠️ 只 `import jieba` 成功并不代表可用 —— 本机 `E:\\Python314` 里装的是
        一个**不完整**的 jieba（有 `cut` 但无 `lcut`），会在真正分词时才抛
        AttributeError。故这里显式校验所需属性，探测失败即整体降级。
        """
        try:
            import jieba  # noqa: F401
            if not hasattr(jieba, "lcut") or not callable(jieba.lcut):
                raise ImportError("jieba 不完整：缺少 lcut")
            from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: F401
            from sklearn.metrics.pairwise import cosine_similarity  # noqa: F401
            import numpy as np  # noqa: F401
            self._use_tfidf = True
        except (ImportError, AttributeError):
            self._use_tfidf = False

    def _tokenize(self, text: str) -> str:
        """分词：优先 jieba，缺失/不完整时降级到项目共享分词器。

        降级路径复用 `ai.eval.tokenize`（中文按字、英文按词），
        保证全项目分词口径一致 —— 这也是 perplexity 可比性的前提。
        """
        try:
            import jieba
            return " ".join(jieba.lcut(text))
        except (ImportError, AttributeError):
            from ..eval.tokenize import tokenize
            return " ".join(tokenize(text))

    def _build_index(self, rules: List[Dict[str, Any]]):
        if not self._use_tfidf:
            return
        from sklearn.feature_extraction.text import TfidfVectorizer

        corpus: List[str] = []
        self._corpus_answers = []
        for rule in rules:
            pattern = rule.get("pattern", "")
            responses = rule.get("responses", [])
            if responses:
                corpus.append(pattern)
                self._corpus_answers.append(random.choice(responses))
        if not corpus:
            self._vectorizer = None
            self._matrix = None
            return
        texts = [self._tokenize(t) for t in corpus]
        self._vectorizer = TfidfVectorizer()
        self._matrix = self._vectorizer.fit_transform(texts)

    # ============================================================
    # 核心匹配（返回 MatchResult）
    # ============================================================
    def match(self, text: str, rules: List[Dict[str, Any]]) -> Optional[MatchResult]:
        if self._use_tfidf:
            return self._match_tfidf(text, rules)
        return self._match_hybrid(text, rules)

    def _match_tfidf(self, text: str, rules: List[Dict[str, Any]]) -> Optional[MatchResult]:
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity

        if self._vectorizer is None:
            self._build_index(rules)
        if self._vectorizer is None or self._matrix is None:
            return None

        vec = self._vectorizer.transform([self._tokenize(text)])
        sims = cosine_similarity(vec, self._matrix)[0]
        best_idx = int(np.argmax(sims))
        score = float(sims[best_idx])

        if score >= self.min_confidence:
            return MatchResult(
                reply=self._corpus_answers[best_idx],
                confidence=score,
                source=self.name
            )
        return None

    def _match_hybrid(self, text: str, rules: List[Dict[str, Any]]) -> Optional[MatchResult]:
        """混合匹配策略：N-Gram Jaccard + 关键词加权 + 编辑距离。

        优先使用 N-Gram Jaccard（对中文更友好），
        叠加关键词权重提升匹配质量。
        """
        best_score = 0.0
        best_answer: Optional[str] = None

        user_keywords = self._extract_content_words(text)

        for rule in rules:
            pattern = rule.get("pattern", "")
            responses = rule.get("responses", [])
            if not responses or pattern == ".*":
                continue

            # 从 pattern 提取可匹配文本
            clean = self._extract_keywords(pattern)
            if not clean:
                continue

            # 策略 1: 字符 N-Gram Jaccard 相似度
            ngram_score = self._ngram_jaccard_similarity(text, clean, self._ngram_n)

            # 策略 2: 关键词权重加成
            keyword_bonus = self._keyword_overlap_score(user_keywords, clean)

            # 策略 3: 编辑距离（降级权重）
            edit_score = self._similarity(text, clean) * 0.5

            # 综合评分：N-Gram 权重最高
            combined = ngram_score * 0.5 + keyword_bonus * 0.3 + edit_score * 0.2

            if combined > best_score and combined >= self.min_confidence:
                best_score = combined
                best_answer = random.choice(responses)

        if best_answer is not None and best_score >= self.min_confidence:
            return MatchResult(reply=best_answer, confidence=best_score, source=self.name)
        return None

    # ============================================================
    # 相似度计算（增强版）
    # ============================================================
    def _ngram_jaccard_similarity(self, a: str, b: str, n: int = 3) -> float:
        """字符 N-Gram Jaccard 相似度。

        将文本拆分为字符 n-gram，计算 Jaccard 系数。
        相比编辑距离，对中文更友好（能捕捉局部共现模式）。

        Example:
            "机器学习" 的 trigram: {"机器学", "器学习"}
            "深度学习" 的 trigram: {"深度学", "度学习"}
            Jaccard = 0（无共同 trigram）
            "机器学习" vs "机器学习算法" -> 高相似度
        """
        if not a or not b:
            return 0.0

        def get_ngrams(s: str, n: int) -> Set[str]:
            s = re.sub(r'[\s\d]+', '', s)
            if len(s) < n:
                return {s}
            return {s[i:i+n] for i in range(len(s) - n + 1)}

        a_ngrams = get_ngrams(a, n)
        b_ngrams = get_ngrams(b, n)

        if not a_ngrams or not b_ngrams:
            return 0.0

        intersection = a_ngrams & b_ngrams
        union = a_ngrams | b_ngrams

        return len(intersection) / len(union)

    def _keyword_overlap_score(self, user_keywords: Set[str], pattern_text: str) -> float:
        """关键词重叠度评分（增强）。"""
        if not user_keywords:
            return 0.0

        overlap = 0
        for kw in user_keywords:
            if kw in pattern_text:
                overlap += 1

        if not overlap:
            return 0.0

        # 重叠比例 + 长度加成（更长的关键词匹配更有价值）
        return min(overlap / len(user_keywords), 1.0) * 0.7 + 0.3

    def _extract_content_words(self, text: str) -> Set[str]:
        """提取内容词（过滤停用词后的关键词集合）。

        用于增强关键词匹配——优先匹配"实词"而非虚词。
        """
        # 简单停用词表
        stop_words = {
            '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一',
            '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着',
            '没有', '看', '好', '自己', '这', '他', '她', '它', '们', '那', '些',
            '什么', '怎么', '哪', '吗', '吧', '呢', '啊', '哦', '嗯', '哈',
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'can', 'could', 'should', 'may', 'might', 'shall', 'to', 'of',
            'in', 'on', 'at', 'for', 'with', 'by', 'from', 'as', 'but',
            'or', 'and', 'not', 'no', 'if', 'so', 'than', 'then', 'that',
            'this', 'these', 'those', 'it', 'its', 'we', 'our', 'you', 'your',
        }

        # 提取所有有意义的词（中文2字以上 + 英文词 + 数字词）
        words = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{2,}', text.lower())
        return {w for w in words if w not in stop_words}

    def _extract_keywords(self, pattern: str) -> str:
        keywords = re.findall(r'[\u4e00-\u9fa5a-zA-Z]+', pattern)
        filtered = [kw for kw in keywords if len(kw) >= 2 and kw != ".*"]
        return " ".join(filtered)

    def _similarity(self, a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        dist = self._levenshtein(a, b)
        max_len = max(len(a), len(b))
        return 1.0 - dist / max_len

    @staticmethod
    def _levenshtein(a: str, b: str) -> int:
        m, n = len(a), len(b)
        prev = list(range(n + 1))
        curr = [0] * (n + 1)
        for i in range(1, m + 1):
            curr[0] = i
            for j in range(1, n + 1):
                cost = 0 if a[i - 1] == b[j - 1] else 1
                curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
            prev, curr = curr, prev
        return prev[n]

    def refresh(self, rules: List[Dict[str, Any]]):
        """重建 TF-IDF 索引。"""
        self._vectorizer = None
        self._matrix = None
        self._corpus_answers = []
        self._build_index(rules)
