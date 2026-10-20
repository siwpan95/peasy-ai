"""
共享分词器 —— 全项目唯一真相来源。

为什么单独抽出来：语言模型的 perplexity **只有在 train / test 使用同一套分词
时才可比较**（分词不同 → token 数不同 → 似然不同，两个数字放在一起没有意义）。
本项目所有建模 / 评估路径（Markov、Neural、eval）都必须调用这里的 tokenize。

策略：中文按字切分，英文按单词，数字成串，其余非空白字符单列。
中文按字而非按词，是为了在只有几千字的语料规模下不至于把 vocab 撑爆。
"""

import re
from typing import List

# 中文字符 | 英文单词 | 数字串 | 其它单个非空白字符
_TOKEN_RE = re.compile(r'[\u4e00-\u9fff]|[a-zA-Z]+|\d+|[^\s]')

# 句边界标记：用于让模型区分句首/句尾，避免生成时开头不合理
BOS = "<s>"
EOS = "</s>"
# 未登录词兜底：低频词与留出集新词统一折叠到此，避免概率归零
UNK = "<unk>"
# 条件分隔标记：用于「问题 → 回答」的条件语言模型，隔开条件与生成部分
SEP = "<sep>"


def tokenize(text: str) -> List[str]:
    """把文本切成 token 列表。空文本返回空列表。"""
    if not text:
        return []
    return [t for t in _TOKEN_RE.findall(text) if t.strip()]


def tokenize_with_bounds(text: str) -> List[str]:
    """带句边界标记的切分（供语言建模训练使用）。"""
    return [BOS] + tokenize(text) + [EOS]


def detokenize(tokens: List[str]) -> str:
    """还原为中文可读文本：中文/标点直接拼接，英文单词之间补空格。"""
    out = []
    for i, t in enumerate(tokens):
        if t in (BOS, EOS, UNK, SEP):
            continue
        if out and _needs_space(out[-1], t):
            out.append(" ")
        out.append(t)
    return "".join(out)


def _needs_space(prev: str, cur: str) -> bool:
    """判断两个 token 之间是否需要补空格（仅英文/数字之间需要）。"""
    if not prev or not cur:
        return False
    p_is_cjk = bool(re.match(r'[\u4e00-\u9fff]', prev))
    c_is_cjk = bool(re.match(r'[\u4e00-\u9fff]', cur))
    if p_is_cjk or c_is_cjk:
        return False
    p_is_word = bool(re.match(r'^[a-zA-Z0-9]+$', prev))
    c_is_word = bool(re.match(r'^[a-zA-Z0-9]+$', cur))
    return p_is_word and c_is_word
