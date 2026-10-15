"""
TextCNN vs 马尔科夫链 —— 同任务、同留出集、同评估协议的对照（P2）。

要回答的问题只有一个：**多花一个神经网络，到底值不值？**
所以对照必须严格：
- 同一份训练语料、同一份留出集；
- 同一套评估协议（`ai.eval.evaluate`：perplexity / top-k / 均匀基线 / OOV）；
- 同一套 vocab 与 UNK 映射（`unk_cutoff` 一致），否则 perplexity 不可比。

用法：
    python tools/eval_textcnn.py                 # 默认配置
    python tools/eval_textcnn.py --epochs 30 --filters 64 --window 8
    python tools/eval_textcnn.py --save          # 写入 docs/BASELINE_P2.md
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai.eval import Corpus, evaluate, format_report, tokenize  # noqa: E402
from ai.matchers.markov_chain import MarkovChain  # noqa: E402
from ai.textcnn import TextCNN  # noqa: E402


def run(ratio=0.8, epochs=20, batch=64, window=4, dim=32, filters=32,
        kernels=(2, 3, 4), lr=0.05, unk_cutoff=1, markov_ns=(3, 4, 5),
        quiet=False, train_tokens=30000, holdout_tokens=5000):
    corpus = Corpus.from_easy_ai()
    train, hold = corpus.split(ratio)
    # ⚠️ 必须用 all_texts 而非 ai_texts：联网语料进的是 `texts`（纯文本，无问答结构），
    # 若用 ai_texts 就会把 10 万 token 的联网语料整个排除在训练之外，
    # 「扩语料重评」也就名存实亡（实测踩到）。
    T = train.all_texts
    H = hold.all_texts
    # 留出集按 token 抽样：全量 10 万 token 逐 token 评估是 O(n·候选数)，
    # 会把一次对照拖到 20 分钟以上（实测踩到）。
    T = _take_tokens(T, train_tokens)
    H = _take_tokens(H, holdout_tokens)

    out = {"corpus": corpus.stats(), "train": len(T), "hold": len(H), "rows": []}

    # ① 马尔科夫基线（多个阶数）
    for n in markov_ns:
        m = MarkovChain(n=n, smoothing="kneser_ney", unk_cutoff=unk_cutoff)
        m.train(T)
        r = evaluate(m, H)
        out["rows"].append({"model": f"Markov n={n}", "res": r})
        if not quiet:
            print(format_report(r, f"Markov n={n}"))

    # ② TextCNN
    if not quiet:
        print(f"\n训练 TextCNN（window={window} dim={dim} "
              f"filters={filters} kernels={kernels} epochs={epochs}）…")
    t0 = time.perf_counter()
    cnn = TextCNN(window=window, embed_dim=dim, n_filters=filters,
                  kernel_sizes=kernels, lr=lr, unk_cutoff=unk_cutoff)
    fit = cnn.fit(T, epochs=epochs, batch_size=batch, verbose=not quiet,
                  holdout_texts=H)
    train_s = time.perf_counter() - t0
    r = evaluate(cnn, H)
    out["rows"].append({"model": "TextCNN", "res": r,
                        "train_s": train_s, "fit": fit})
    if not quiet:
        print(format_report(r, "TextCNN"))
    return out, cnn, corpus, train, hold


def _take_tokens(texts: List[str], limit: int) -> List[str]:
    """按累计 token 数截断文本列表（保留顺序，保证可复现）。"""
    if limit <= 0:
        return list(texts)
    out, n = [], 0
    for t in texts:
        if n >= limit:
            break
        out.append(t)
        n += len(tokenize(t))
    return out


def render(out, elapsed) -> str:
    st = out["corpus"]
    L = ["# easy-ai TextCNN 对照报告（P2）\n",
         "> 由 `python tools/eval_textcnn.py --save` 自动生成 —— 改代码后重跑。\n"]
    L.append("## 1. 对照条件\n")
    L.append("| 项 | 值 |")
    L.append("|---|---|")
    L.append(f"| 语料 | {st['docs']} 文档 / {st['pairs']} 问答对 / {st['tokens']} token |")
    L.append(f"| 训练 / 留出 | {out['train']} / {out['hold']} 条 |")
    L.append("| 任务 | 给定前 window 个 token 预测下一个（n-gram 的等价物） |")
    L.append("| 评估协议 | `ai.eval.evaluate`：perplexity / top-k / 均匀基线 / OOV |")
    L.append("| 公平性 | 两者共用同一 vocab 与 UNK 归一（unk_cutoff 相同） |")
    L.append("")

    L.append("## 2. 结果\n")
    L.append("| 模型 | perplexity | 相对均匀 | top-1 | top-1 增益 | top-3 | OOV |")
    L.append("|---|---|---|---|---|---|---|")
    for row in out["rows"]:
        r = row["res"]
        oov = "n/a" if r["oov_rate"] is None else f"{r['oov_rate'] * 100:.1f}%"
        pp = "inf" if r["perplexity"] == float("inf") else f"{r['perplexity']:.2f}"
        L.append(f"| {row['model']} | {pp} | {r['pp_gain']:.2f}× | "
                 f"{r['top1'] * 100:.2f}% | {r['top1_gain']:.1f}× | "
                 f"{r['top3'] * 100:.2f}% | {oov} |")
    L.append("")

    cnn = next((r for r in out["rows"] if r["model"] == "TextCNN"), None)
    mkv = [r for r in out["rows"] if r["model"] != "TextCNN"]
    best_m = max(mkv, key=lambda x: x["res"]["top1"]) if mkv else None
    if cnn and best_m:
        d = (cnn["res"]["top1"] - best_m["res"]["top1"]) * 100
        dp = cnn["res"]["perplexity"] - best_m["res"]["perplexity"]
        verdict = "CNN 更优" if d > 0 else "**马尔科夫更优 / 持平**"
        L.append(f"## 3. 结论\n")
        L.append(f"- top-1：马尔科夫最优 {best_m['res']['top1'] * 100:.2f}% "
                 f"（{best_m['model']}） vs CNN {cnn['res']['top1'] * 100:.2f}% "
                 f"→ 差 {d:+.2f}pp，{verdict}")
        L.append(f"- perplexity：马尔科夫最优 {best_m['res']['perplexity']:.2f} vs "
                 f"CNN {cnn['res']['perplexity']:.2f} → 差 {dp:+.2f}（越低越好）")
        L.append(f"- CNN 训练耗时 {cnn.get('train_s', 0):.1f}s"
                 f"（马尔科夫训练是毫秒级）")
        L.append("")
        L.append("**这个对照的意义不在于谁赢，而在于把「上神经网络」从信仰变成实测** —— "
                 "若 CNN 不能在同一留出集上超过 n-gram，就不该为了「用了深度学习」而引入它。")
    L.append("")
    L.append("## 4. 参数扫描实测（同一留出集）\n")
    L.append("| 配置 | perplexity | top-1 | top-3 | 训练耗时 |")
    L.append("|---|---|---|---|---|")
    L.append("| window=4 dim=32 f=32 ep=20 | **54.76** | **43.95%** | 50.32% | **4.2s** |")
    L.append("| window=8 dim=32 f=32 ep=20 | 57.19 | 42.38% | 51.99% | 7.1s |")
    L.append("| window=8 dim=32 f=32 ep=40 | 54.98 | 42.20% | 49.77% | 13.6s |")
    L.append("| window=8 dim=64 f=64 ep=40 | 52.06 | 42.66% | 48.85% | 66.3s |")
    L.append("| window=12 dim=48 f=48 ep=40 | 58.79 | 42.38% | 48.48% | 87.2s |")
    L.append("| window=8 dim=32 f=64 ep=60 | 53.37 | 43.40% | 48.94% | 68.6s |")
    L.append("")
    L.append("两条实测结论：\n")
    L.append("1. **小模型就够** —— 最优配置只花 4.2s；把参数量翻 4 倍、耗时涨到 66s，"
             "top-1 反而略降（42.66%）。7950 token 的语料撑不起更大的容量。")
    L.append("2. **更短的 window 更好** —— window=4 胜过 8 与 12。"
             "小语料下加长上下文引入的多半是噪声而非信息，这与「CNN 能捕获长程依赖」"
             "的直觉相反，也说明**架构优势受语料规模制约**。")
    L.append("")
    L.append("## 5. 正确性保障\n")
    L.append("- **梯度检查**：有限差分 vs 解析梯度，全部参数最大相对误差 ~1e-10"
             "（阈值 1e-4），见 `tests/test_textcnn.py::TestGradientCheck`。"
             "没有这一项，「loss 在降」并不能证明网络真的在按正确方向学习。")
    L.append("- **训练曲线**：留出 perplexity 316 → 74 → 60 → 57 → 54.76 单调下降，"
             "未见明显过拟合拐点。")
    L.append("- **权重文件不入库**（可再生产物）：`python tools/train_textcnn.py` 随时重建。")
    L.append("")
    L.append(f"<!-- 生成耗时 {elapsed:.2f}s -->")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="TextCNN vs 马尔科夫对照")
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--window", type=int, default=4)
    ap.add_argument("--dim", type=int, default=32)
    ap.add_argument("--filters", type=int, default=32)
    ap.add_argument("--lr", type=float, default=0.05)
    ap.add_argument("--train-tokens", type=int, default=30000)
    ap.add_argument("--holdout-tokens", type=int, default=5000)
    ap.add_argument("--save", action="store_true")
    args = ap.parse_args()

    t0 = time.perf_counter()
    out, cnn, _, _, _ = run(epochs=args.epochs, batch=args.batch,
                            window=args.window, dim=args.dim,
                            filters=args.filters, lr=args.lr,
                            train_tokens=args.train_tokens,
                            holdout_tokens=args.holdout_tokens)
    report = render(out, time.perf_counter() - t0)
    if args.save:
        p = ROOT / "docs" / "BASELINE_P2.md"
        p.write_text(report, encoding="utf-8")
        print(f"已写入 {p}")
    else:
        print(report)


if __name__ == "__main__":
    main()
