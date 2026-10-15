"""
TextCNN 离线训练器 —— 把权重训好存盘，供运行期直接加载。

为什么离线训：TextCNN 在 7950 token 语料上训练需数秒（Markov 只需毫秒级），
放进 AICore 启动路径会明显拖慢「零参数启动」。所以拆成两步：
    离线：python tools/train_textcnn.py --out data/textcnn_weights.json
    运行期：加载权重（毫秒级），可选参与匹配器竞争。

用法：
    python tools/train_textcnn.py
    python tools/train_textcnn.py --epochs 60 --filters 64 --window 8
    python tools/train_textcnn.py --out data/textcnn_weights.json --report
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai.eval import Corpus, evaluate, format_report  # noqa: E402
from ai.textcnn import TextCNN  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="训练 TextCNN 并导出权重")
    ap.add_argument("--out", default=str(ROOT / "data" / "textcnn_weights.json"))
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--window", type=int, default=8)
    ap.add_argument("--dim", type=int, default=32)
    ap.add_argument("--filters", type=int, default=32)
    ap.add_argument("--lr", type=float, default=0.05)
    ap.add_argument("--ratio", type=float, default=0.8)
    ap.add_argument("--no-paotuan", action="store_true", help="训练语料排除 paotuan")
    ap.add_argument("--full", action="store_true",
                    help="用全量语料训练（不划分留出）。**生产权重必须用它** —— "
                         "否则导出的权重没见过留出部分，运行期检索到那些原文时会给出"
                         "很低的概率，导致 neural 匹配器永远输给马尔科夫（实测踩到）。")
    ap.add_argument("--report", action="store_true", help="打印留出集评估报告")
    ap.add_argument("--conditional", action="store_true",
                    help="训练条件模型 P(回答|问题)（序列为 `[BOS] 问题 SEP 回答 EOS`）。"
                         "**重排序打分必须用条件模型** —— 用无条件模型打分时"
                         "训练与推理的 context 分布不一致，实测 top-1 仅 5%（条件化后 40%）。")
    args = ap.parse_args()

    corpus = Corpus.from_easy_ai(include_paotuan=not args.no_paotuan)
    conditions = None
    out_path = Path(args.out)
    if args.conditional:
        conditions = [p.question for p in corpus.pairs]
        if args.out == str(ROOT / "data" / "textcnn_weights.json"):
            out_path = ROOT / "data" / "textcnn_rerank_weights.json"
    if args.full:
        T = corpus.ai_texts or corpus.all_texts
        H = []
        print(f"语料 {corpus}  →  **全量训练** {len(T)} 条（无留出，用于生产权重）")
    else:
        train, hold = corpus.split(args.ratio)
        T = train.ai_texts or train.all_texts
        H = hold.all_texts
        print(f"语料 {corpus}  →  训练 {len(T)} 条 / 留出 {len(H)} 条")

    t0 = time.perf_counter()
    m = TextCNN(window=args.window, embed_dim=args.dim,
                n_filters=args.filters, lr=args.lr, unk_cutoff=1)
    cond = conditions[:len(T)] if conditions else None
    fit = m.fit(T, epochs=args.epochs, batch_size=args.batch, verbose=True,
                holdout_texts=H if H else None, conditions=cond)
    dt = time.perf_counter() - t0
    print(f"\n训练完成：{fit['samples']} 样本 / 词表 {fit['vocab']} / 耗时 {dt:.1f}s")

    if args.report and H:
        print()
        print(format_report(evaluate(m, H), "TextCNN 留出集"))
    elif args.report:
        print("\n（--full 模式无留出集，跳过评估报告；"
              "要评估请不加 --full，改用 tools/eval_textcnn.py）")

    out = out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out_path))
    size_kb = out_path.stat().st_size / 1024
    print(f"\n权重已写入 {out_path}（{size_kb:.0f} KB）")
    print("运行期加载：")
    print(f"    from ai.textcnn import TextCNN; m = TextCNN.load(r'{out_path}')")


if __name__ == "__main__":
    main()
