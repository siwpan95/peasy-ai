"""
ai.eval —— 评估地基（P0）。

先有可判定的尺子，再有可证明的改进。本包提供：
- `tokenize`   : 全项目唯一分词器（train/test 必须同源，否则 perplexity 不可比）
- `Corpus`     : 多源语料加载 + 按文档留出集划分
- `metrics`    : perplexity / top-k / 均匀基线 / 相对增益 / 覆盖率 / OOV

口径源自 `weiqi_lab` 的 Tier-3 实践（docs/TIER3_LEARNING.md §2.6）：
那次「对称帧未归一」的语义缺陷之所以能被发现并量化（top-1 7.25% → 21.34%），
靠的就是「留出集 + 均匀基线 + 相对增益 + 合成可判定用例」这套尺子。
"""

from .tokenize import tokenize, tokenize_with_bounds, detokenize, BOS, EOS, UNK, SEP
from .corpus import Corpus, QAPair
from .metrics import (
    perplexity,
    mean_log_prob,
    top_k_accuracy,
    oov_rate,
    coverage,
    uniform_baseline,
    relative_gain,
    evaluate,
    format_report,
)

__all__ = [
    "tokenize", "tokenize_with_bounds", "detokenize", "BOS", "EOS", "UNK", "SEP",
    "Corpus", "QAPair",
    "perplexity", "mean_log_prob", "top_k_accuracy", "oov_rate", "coverage",
    "uniform_baseline", "relative_gain", "evaluate", "format_report",
]
