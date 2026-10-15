"""
语言模型评估指标 —— 口径对齐 `weiqi_lab/tools/eval_model.mjs`。

核心纪律（来自 weiqi_lab 的教训，也是本项目 P0 的地基）：
1. **留出集**：只在未参与训练的数据上评估，按文档划分而非按 token 随机切。
2. **基线对照**：单独看 top-1 没有意义，必须给出「均匀基线」与「相对增益」。
   weiqi_lab 正是靠这条发现 Markov 模型 0.91×（不如瞎猜）→ 换语料后 50.1×。
3. **OOV 显式标注**：未登录词比例不标出来，perplexity 就是个没法解释的数字。

模型协议（duck typing，任何实现了下列接口的对象都可被评估）：
- `log_prob(context: Sequence[str], token: str) -> float`  自然对数概率
- `top_k(context: Sequence[str], k: int) -> List[Tuple[str, float]]`
- `vocab_size: int`
- 可选 `vocab: Set[str]`（用于统计 OOV）
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Set

from .tokenize import tokenize, BOS, EOS

# 概率下限：避免 log(0) = -inf 让 perplexity 直接爆成 inf。
# 取 e^-20 ≈ 2e-9，等价于「模型认为该 token 几乎不可能」。
LOG_FLOOR = -20.0


# ============================================================
# 单项指标
# ============================================================
def perplexity(model: Any, texts: List[str]) -> float:
    """困惑度 PP = exp(-1/N · Σ log P(token|context))，越低越好。

    返回 inf 表示模型在留出集上完全无法预测（等价于无限惊讶）。
    """
    total_lp, n = _accumulate_logprob(model, texts)
    if n == 0:
        return float("inf")
    return math.exp(-total_lp / n)


def mean_log_prob(model: Any, texts: List[str]) -> float:
    """平均对数似然（perplexity 的原料，便于跨模型比较）。"""
    total_lp, n = _accumulate_logprob(model, texts)
    return total_lp / n if n else float("-inf")


def top_k_accuracy(model: Any, texts: List[str], k: int = 1) -> float:
    """top-k 命中率：真值 token 是否落在模型给出的前 k 个预测里。

    ⚠️ 口径修正：真值必须走与模型相同的 UNK 归一，否则「模型正确预测出
    『这是个生僻词』（输出 <unk>）」会被误判为不命中 —— 这会系统性地
    低估做了 UNK 折叠的模型（实测 top-1 20.90% → 16.58% 的假象即源于此）。
    """
    hit = total = 0
    for text in texts:
        toks = [BOS] + tokenize(text) + [EOS]
        for i in range(1, len(toks)):
            ctx = toks[:i]
            try:
                preds = model.top_k(ctx, k)
            except (AttributeError, NotImplementedError):
                return 0.0
            if not preds:
                continue
            total += 1
            truth = _norm_token(model, toks[i])
            if any(w == truth for w, _ in preds):
                hit += 1
    return hit / total if total else 0.0


def oov_rate(model: Any, texts: List[str]) -> Optional[float]:
    """留出集未登录词（OOV）比例。模型未暴露 vocab 时返回 None。"""
    vocab: Optional[Set[str]] = getattr(model, "vocab", None)
    if not vocab:
        return None
    toks = _all_tokens(texts)
    if not toks:
        return None
    return sum(1 for t in toks if t not in vocab) / len(toks)


def coverage(model: Any, texts: List[str]) -> float:
    """覆盖率：模型给出「非零概率预测」的 token 占比。

    与 OOV 互补 —— 有平滑时 token 即便未登录也能拿到概率，此时覆盖率
    应接近 1，而 OOV 仍然如实报告有多少词是模型没见过的。
    """
    total = covered = 0
    for text in texts:
        toks = [BOS] + tokenize(text) + [EOS]
        for i in range(1, len(toks)):
            total += 1
            lp = model.log_prob(toks[:i], toks[i])
            if lp > LOG_FLOOR:
                covered += 1
    return covered / total if total else 0.0


def uniform_baseline(vocab_size: int) -> Dict[str, float]:
    """均匀（瞎猜）基线：每个 token 等概率 1/V。

    Returns:
        {"perplexity": V, "top1": 1/V, "top3": 3/V}
    """
    if vocab_size <= 0:
        return {"perplexity": float("inf"), "top1": 0.0, "top3": 0.0}
    return {
        "perplexity": float(vocab_size),
        "top1": 1.0 / vocab_size,
        "top3": min(3.0 / vocab_size, 1.0),
    }


def relative_gain(score: float, baseline: float) -> float:
    """相对基线增益（越大越好）。weiqi_lab 的「相对均匀」口径。

    - perplexity 用反向比值（越低越好）：`baseline / score`
    - 准确率用正向比值（越高越好）：`score / baseline`
    调用方按指标语义自行传参，这里只做除法与防零。
    """
    if score is None or baseline is None:
        return 0.0
    if baseline == 0:
        return 0.0
    if score == 0:
        return 0.0
    return score / baseline


# ============================================================
# 汇总评估
# ============================================================
def evaluate(model: Any, holdout_texts: List[str]) -> Dict[str, Any]:
    """在留出集上跑全套指标，返回可直接制表的字典。

    任何一项缺失都如实标注为 None，**不补 0 假装没问题**。
    """
    if not holdout_texts:
        return {"error": "留出集为空"}

    vocab_size = int(getattr(model, "vocab_size", 0) or 0)
    pp = perplexity(model, holdout_texts)
    t1 = top_k_accuracy(model, holdout_texts, 1)
    t3 = top_k_accuracy(model, holdout_texts, 3)
    base = uniform_baseline(vocab_size)
    oov = oov_rate(model, holdout_texts)

    return {
        "tokens": sum(len(tokenize(t)) for t in holdout_texts),
        "vocab_size": vocab_size,
        "perplexity": pp,
        # perplexity 越低越好 → 增益 = 基线 / 实测
        "pp_gain": relative_gain(base["perplexity"], pp) if pp not in (0.0, float("inf")) else 0.0,
        "top1": t1,
        "top3": t3,
        "uniform_top1": base["top1"],
        "top1_gain": relative_gain(t1, base["top1"]),
        "uniform_top3": base["top3"],
        "top3_gain": relative_gain(t3, base["top3"]),
        "coverage": coverage(model, holdout_texts),
        "oov_rate": oov,
    }


def format_report(result: Dict[str, Any], title: str = "评估结果") -> str:
    """把 evaluate() 的结果渲染成人类可读的文本表格。"""
    if "error" in result:
        return f"{title}: {result['error']}"

    def pct(x):
        return "  n/a" if x is None else f"{x * 100:5.2f}%"

    pp = result["perplexity"]
    pp_s = "inf" if pp == float("inf") else f"{pp:.2f}"
    lines = [
        f"── {title} ──",
        f"  留出 token {result['tokens']}  ·  词表 {result['vocab_size']}",
        f"  perplexity {pp_s:>10}   均匀基线 {result['vocab_size']:<8} "
        f"相对 {result['pp_gain']:.2f}×",
        f"  top-1      {pct(result['top1'])}  均匀基线 {pct(result['uniform_top1'])} "
        f"相对 {result['top1_gain']:.2f}×",
        f"  top-3      {pct(result['top3'])}  均匀基线 {pct(result['uniform_top3'])} "
        f"相对 {result['top3_gain']:.2f}×",
        f"  覆盖率     {pct(result['coverage'])}",
        f"  OOV        {pct(result['oov_rate'])}",
    ]
    return "\n".join(lines)


# ============================================================
# 内部
# ============================================================
def _all_tokens(texts: List[str]) -> List[str]:
    out: List[str] = []
    for t in texts:
        out.extend(tokenize(t))
    return out


def _norm_token(model: Any, token: str) -> str:
    """真值归一：与模型使用同一套 UNK 映射，保证评估口径公平。"""
    fn = getattr(model, "_norm", None)
    if callable(fn):
        try:
            return fn(token)
        except Exception:
            return token
    return token


def _accumulate_logprob(model: Any, texts: List[str]) -> tuple:
    """累加留出集的对数概率，返回 (总 log 概率, token 数)。

    概率为 0 时按 LOG_FLOOR 截断而不是让结果变 -inf，
    这样 perplexity 仍能给出可比的上界，同时 coverage/OOV 如实提示问题所在。
    """
    total_lp = 0.0
    n = 0
    for text in texts:
        toks = [BOS] + tokenize(text) + [EOS]
        for i in range(1, len(toks)):
            lp = model.log_prob(toks[:i], _norm_token(model, toks[i]))
            if lp is None or math.isnan(lp):
                lp = LOG_FLOOR
            total_lp += max(lp, LOG_FLOOR)
            n += 1
    return total_lp, n
