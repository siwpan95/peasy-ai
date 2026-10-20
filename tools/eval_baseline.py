"""
基线评估器 —— 跑出「当前这把尺子的刻度」，供后续所有改进对照。

为什么需要它：weiqi_lab 的教训是，没有基线就无法判定改进是否真实。
本脚本把「语料 × 平滑 × UNK 折叠 × n 阶」的网格结果固定成一份可复现的报告，
P1（扩语料）与 P2（上 CNN）的每一步都拿它当对照组。

用法：
    python tools/eval_baseline.py                  # 打印报告
    python tools/eval_baseline.py --save           # 同时写入 docs/BASELINE_P0.md
    python tools/eval_baseline.py --ratio 0.8 --n 2 3 4 5

口径：
- 留出集按文档划分（前 80% 训练 / 后 20% 留出），确定性可复现；
- 所有指标同时给出**均匀基线**与**相对增益**，单独看绝对值没有意义；
- OOV 率必须一起报告 —— 不标 OOV 的 perplexity 无法解释。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from easy_ai.ai.eval import Corpus, evaluate, format_report  # noqa: E402
from easy_ai.ai.matchers.markov_chain import MarkovChain  # noqa: E402


def run_grid(train_texts, hold_texts, ns, smoothings, cutoffs):
    """跑参数网格，返回结果列表（按 top-1 降序）。"""
    rows = []
    for n in ns:
        for sm in smoothings:
            for cut in cutoffs:
                t0 = time.perf_counter()
                m = MarkovChain(n=n, smoothing=sm, unk_cutoff=cut)
                m.train(train_texts)
                train_ms = (time.perf_counter() - t0) * 1000
                r = evaluate(m, hold_texts)
                rows.append({
                    "n": n, "smoothing": sm, "cutoff": cut,
                    "vocab": r["vocab_size"],
                    "perplexity": r["perplexity"],
                    "pp_gain": r["pp_gain"],
                    "top1": r["top1"], "top3": r["top3"],
                    "top1_gain": r["top1_gain"],
                    "coverage": r["coverage"],
                    "oov": r["oov_rate"],
                    "train_ms": train_ms,
                })
    return rows


def render(corpus, train, hold, rows, elapsed) -> str:
    st = corpus.stats()
    L = []
    L.append("# easy-ai 学习组件基线报告（P0）\n")
    L.append("> 由 `python tools/eval_baseline.py --save` 自动生成 —— 请勿手改，改代码后重跑。\n")

    L.append("## 1. 语料（项目内真实事件流）\n")
    L.append("| 项 | 值 |")
    L.append("|---|---|")
    L.append(f"| 纯文本文档 | {st['docs']} |")
    L.append(f"| 问答对 | {st['pairs']} |")
    L.append(f"| 字符数 | {st['chars']} |")
    L.append(f"| token 数 | {st['tokens']} |")
    L.append(f"| 来源分布 | {st['sources']} |")
    L.append(f"| 训练集 | {len(train.texts)} 文档 / {len(train.pairs)} 对 |")
    L.append(f"| 留出集 | {len(hold.texts)} 文档 / {len(hold.pairs)} 对 |")
    L.append("")
    L.append("**语料是当前最大的瓶颈**：仅数千 token，留出集 OOV 率居高不下。"
             "这与 weiqi_lab 的实测结论一致 —— 语料质量/规模是第一序位杠杆"
             "（同一模型换语料，相对增益 1.34× → 50.1×），远大于换模型架构的收益。\n")

    L.append("## 2. 参数网格（留出集口径）\n")
    L.append("| n | 平滑 | UNK cutoff | 词表 | perplexity | 相对均匀 | top-1 | top-1 增益 | top-3 | 覆盖率 | OOV |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda x: -x["top1"]):
        oov = "n/a" if r["oov"] is None else f"{r['oov'] * 100:.1f}%"
        pp = "inf" if r["perplexity"] == float("inf") else f"{r['perplexity']:.2f}"
        L.append(
            f"| {r['n']} | {r['smoothing']} | {r['cutoff']} | {r['vocab']} | {pp} | "
            f"{r['pp_gain']:.2f}× | {r['top1'] * 100:.2f}% | {r['top1_gain']:.1f}× | "
            f"{r['top3'] * 100:.2f}% | {r['coverage'] * 100:.1f}% | {oov} |"
        )
    L.append("")

    best_pp = min(rows, key=lambda x: x["perplexity"] if x["perplexity"] != float("inf") else 1e18)
    best_top1 = max(rows, key=lambda x: x["top1"])
    L.append("## 3. 结论\n")
    L.append(f"- **perplexity 最优**：n={best_pp['n']} / {best_pp['smoothing']} / "
             f"cutoff={best_pp['cutoff']} → {best_pp['perplexity']:.2f}"
             f"（相对均匀 {best_pp['pp_gain']:.2f}×）")
    L.append(f"- **top-1 最优**：n={best_top1['n']} / {best_top1['smoothing']} / "
             f"cutoff={best_top1['cutoff']} → {best_top1['top1'] * 100:.2f}%"
             f"（相对均匀 {best_top1['top1_gain']:.1f}×）")
    L.append("- **UNK 折叠是最大单项改进**：cutoff 0 → 1 让 perplexity 大幅下降；"
             "但 cutoff 继续增大只会让词表缩水、top-1 下滑，属指标假象，故默认取 1。")
    L.append("- **平滑的取舍**：小语料下每个 context 平均计数≈1，add-k/KN 会稀释已见的确定性转移，"
             "perplexity 反而差于 MLE+回退；但二者 top-1 与最优持平且**消除了零概率**，"
             "故默认仍取 Kneser-Ney（生成采样需要非零分布）。")
    L.append("")
    L.append(f"<!-- 生成耗时 {elapsed:.2f}s -->")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="easy-ai 学习组件基线评估")
    ap.add_argument("--ratio", type=float, default=0.8, help="训练集比例（默认 0.8）")
    ap.add_argument("--n", type=int, nargs="+", default=[2, 3, 4, 5], help="n-gram 阶数")
    ap.add_argument("--smoothing", nargs="+", default=["none", "add_k", "kneser_ney"])
    ap.add_argument("--cutoff", type=int, nargs="+", default=[0, 1], help="UNK 折叠阈值")
    ap.add_argument("--save", action="store_true", help="写入 docs/BASELINE_P0.md")
    args = ap.parse_args()

    t0 = time.perf_counter()
    corpus = Corpus.from_easy_ai()
    train, hold = corpus.split(args.ratio)

    train_texts = train.ai_texts or train.all_texts
    hold_texts = hold.all_texts

    print(f"语料 {corpus}")
    print(f"训练 {len(train_texts)} 条 / 留出 {len(hold_texts)} 条\n")

    rows = run_grid(train_texts, hold_texts, args.n, args.smoothing, args.cutoff)
    elapsed = time.perf_counter() - t0
    report = render(corpus, train, hold, rows, elapsed)

    if args.save:
        out = ROOT / "docs" / "BASELINE_P0.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"已写入 {out}")
    else:
        print(report)


if __name__ == "__main__":
    main()
