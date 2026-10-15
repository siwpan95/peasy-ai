"""
检索索引 —— 马尔科夫匹配器与神经网络匹配器共用的「输入 → 相关历史问答」检索。

为什么抽出来：两个匹配器都需要「用用户输入检索到最相关的历史问答对」，
若各写一份就会有两套倒排索引要维护（而且各自的 bug 要修两次）。

实现是**字符 bigram 倒排索引**：
- 构建 O(语料长度)，查询 O(输入长度)；
- 相关性 = 命中的 bigram 数 / 输入 bigram 数，天然归一到 [0,1]。

它的前身在旧 `markov_chain.py` 里是 O(状态数 × 语料数) 的双重循环
（`_build_corpus_keywords`），另一个 `_build_keyword_index` 干脆是空实现 —— 两者
都在 P0 被本文件取代。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Sequence, Tuple

from ..eval.tokenize import tokenize


class RetrievalIndex:
    """字符 bigram 倒排索引。"""

    def __init__(self):
        self._index: Dict[Tuple[str, str], List[int]] = {}
        self._items: List[str] = []

    # ---------- 构建 ----------
    def build(self, keys: Sequence[str]):
        """用「用户侧」文本构建索引（问句，而非回答）。"""
        self._index.clear()
        self._items = list(keys or [])
        for i, key in enumerate(self._items):
            for g in set(_bigrams(tokenize(key))):
                self._index.setdefault(g, []).append(i)

    # ---------- 查询 ----------
    def retrieve(self, text: str, top_n: int = 3) -> List[Tuple[int, float]]:
        """返回 [(下标, 相关性)]，按相关性降序。"""
        grams = _bigrams(tokenize(text or ""))
        if not grams:
            return []
        hit: Dict[int, int] = defaultdict(int)
        for g in grams:
            for i in self._index.get(g, ()):
                hit[i] += 1
        if not hit:
            return []
        scored = [(i, c / len(grams)) for i, c in hit.items()]
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:top_n]

    # ---------- 属性 ----------
    @property
    def size(self) -> int:
        return len(self._items)

    @property
    def items(self) -> List[str]:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self):
        return f"<RetrievalIndex items={len(self._items)} grams={len(self._index)}>"


def _bigrams(tokens: Sequence[str]) -> List[Tuple[str, str]]:
    """字符/词 bigram；单 token 时复制自身，保证索引非空。"""
    if len(tokens) >= 2:
        return [(tokens[i], tokens[i + 1]) for i in range(len(tokens) - 1)]
    if len(tokens) == 1:
        return [(tokens[0], tokens[0])]
    return []
