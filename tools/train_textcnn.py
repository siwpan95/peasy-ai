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
    ap.add_argument("--report", action="store_true", help="打印留出集评估报告")
    args = ap.parse_args()

    corpus = Corpus.from_easy_ai(include_paotuan=not args.no_paotuan)
    train, hold = corpus.split(args.ratio)
    T = train.ai_texts or train.all_texts
    H = hold.all_texts

    print(f"语料 {corpus}  →  训练 {len(T)} 条 / 留出 {len(H)} 条")

    t0 = time.perf_counter()
    m = TextCNN(window=args.window, embed_dim=args.dim,
                n_filters=args.filters, lr=args.lr, unk_cutoff=1)
    fit = m.fit(T, epochs=args.epochs, batch_size=args.batch, verbose=True,
                holdout_texts=H)
    dt = time.perf_counter() - t0
    print(f"\n训练完成：{fit['samples']} 样本 / 词表 {fit['vocab']} / 耗时 {dt:.1f}s")

    if args.report:
        print()
        print(format_report(evaluate(m, H), "TextCNN 留出集"))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out))
    size_kb = out.stat().st_size / 1024
    print(f"\n权重已写入 {out}（{size_kb:.0f} KB）")
    print("运行期加载：")
    print(f"    from ai.textcnn import TextCNN; m = TextCNN.load(r'{out}')")


if __name__ == "__main__":
    main()
