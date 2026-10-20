"""
TextCNN —— 真·文本卷积神经网络（Kim, EMNLP 2014）。

为什么重写而不复用 `ai/neural.py`：那里 `Conv1DLayer` **从未被实例化过**，
docstring 声称的 `TextCNN` 类根本不存在（P0 审计确认的死代码）。本文件是
第一次真正把它跑起来。

架构（Kim 2014）：
    Embedding → 多尺度 Conv1D(h∈{2,3,4}) → ReLU → Max-over-time pooling
              → Concat → Dropout → Dense → Softmax

与马尔科夫链的**对照口径**（本项目的关键设计）：
两者实现同一套 `ai.eval` 评估协议 —— `log_prob(context, token)` /
`top_k(context, k)` / `vocab_size` / `_norm(token)` —— 因而可以直接用
同一个 `ai.eval.evaluate()` 在同一留出集上对比。任务也对齐为
「给定前 window 个 token，预测下一个 token」，即 n-gram 的等价物。

公平性约束：与 MarkovChain 使用**相同的 vocab 与 UNK 映射**，
否则 perplexity 不可比（分词/词表不同则似然不同，见 ai/eval/tokenize.py）。

依赖：仅 numpy（可选）。缺失时 import 本模块不会炸，实例化时才报错。
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .eval.tokenize import tokenize, detokenize, BOS, EOS, UNK, SEP
from .eval.metrics import LOG_FLOOR

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    np = None
    _HAS_NUMPY = False


PAD = "<pad>"
PAD_ID = 0


class TextCNN:
    """字符级 TextCNN 语言模型（下一 token 预测）。

    与 n-gram 的本质差别：n-gram 是**记忆**「这 n-1 个 token 之后出现过什么」；
    CNN 学的是「哪些局部模式组合指向下一个 token」，因此有希望泛化到
    训练时没见过的 token 组合 —— 这正是 P1 实验2 暴露的 n-gram 天花板所在。
    """

    def __init__(self, window: int = 8, embed_dim: int = 32, n_filters: int = 32,
                 kernel_sizes: Sequence[int] = (2, 3, 4), dropout: float = 0.5,
                 lr: float = 0.05, unk_cutoff: int = 1, seed: int = 0):
        if not _HAS_NUMPY:
            raise ImportError("TextCNN 需要 numpy：`pip install numpy`")

        self.window = int(window)
        self.embed_dim = int(embed_dim)
        self.n_filters = int(n_filters)
        self.kernel_sizes = tuple(int(h) for h in kernel_sizes)
        self.dropout = float(dropout)
        self.lr = float(lr)
        self.unk_cutoff = int(unk_cutoff)
        self.seed = int(seed)

        self._itos: List[str] = []
        self._stoi: Dict[str, int] = {}
        self._kept: Set[str] = set()
        self._trained = False
        self._params: Dict[str, Any] = {}
        self._rng = random.Random(seed)

    # ============================================================
    # 词表（与 MarkovChain 同口径）
    # ============================================================
    def build_vocab(self, texts: List[str]):
        """按与 MarkovChain 相同的 UNK cutoff 构建词表。"""
        freq: Dict[str, int] = {}
        for t in texts:
            for tok in tokenize(t):
                freq[tok] = freq.get(tok, 0) + 1
        kept = {t for t, c in freq.items()
                if (c > self.unk_cutoff if self.unk_cutoff > 0 else True)}
        kept.update((BOS, EOS, UNK, SEP))
        self._kept = kept
        self._itos = [PAD] + sorted(kept)
        self._stoi = {w: i for i, w in enumerate(self._itos)}

    @property
    def vocab_size(self) -> int:
        return len(self._itos)

    @property
    def vocab(self) -> Set[str]:
        """供 ai.eval 统计 OOV。"""
        return set(self._kept)

    def _norm(self, token: str) -> str:
        """与 MarkovChain 同名的 UNK 归一，保证评估口径一致。"""
        return token if token in self._kept else UNK

    def _encode(self, tokens: Sequence[str]) -> List[int]:
        return [self._stoi.get(self._norm(t), self._stoi.get(UNK, PAD_ID))
                for t in tokens]

    # ============================================================
    # 样本构造
    # ============================================================
    def build_samples(self, texts: List[str],
                      conditions: Optional[Sequence[str]] = None
                      ) -> Tuple[np.ndarray, np.ndarray]:
        """构造 (context → next token) 监督样本。

        Args:
            texts: 目标文本（回答）。
            conditions: 与 texts 一一对应的条件前缀（问题）。
                传入时训练的是**条件**语言模型 P(回答|问题)，序列为
                `[BOS] 问题 SEP 回答 EOS`。

        ⚠️ 为什么必须支持 conditions：最初版本只训无条件语言模型，
        却拿它去做 P(回答|问题) 的候选打分 —— 训练与推理的 context 分布
        根本不一致，打分自然失效（实测 top-1 只有 5%，远不如朴素的
        字符 bigram Jaccard 的 60%）。要做条件打分，训练就必须带条件。
        """
        Xs: List[List[int]] = []
        ys: List[int] = []
        for j, text in enumerate(texts):
            cond = conditions[j] if conditions is not None and j < len(conditions) else None
            toks = [BOS] + tokenize(cond or "")
            if cond:
                toks.append(SEP)
            toks += tokenize(text) + [EOS]
            ids = self._encode(toks)
            for i in range(1, len(ids)):
                ctx = ids[max(0, i - self.window):i]
                if len(ctx) < self.window:
                    ctx = [PAD_ID] * (self.window - len(ctx)) + ctx
                Xs.append(ctx)
                ys.append(ids[i])
        return np.array(Xs, dtype=np.int64), np.array(ys, dtype=np.int64)

    # ============================================================
    # 参数初始化
    # ============================================================
    def _init_params(self):
        rng = np.random.RandomState(self.seed)
        V, d = self.vocab_size, self.embed_dim
        scale_e = 0.1
        p = {
            "E": rng.randn(V, d) * scale_e,
        }
        for h in self.kernel_sizes:
            # He 初始化：sqrt(2 / (h*d))
            p[f"W{h}"] = rng.randn(self.n_filters, h, d) * math.sqrt(2.0 / (h * d))
            p[f"b{h}"] = np.zeros(self.n_filters)
        H = self.n_filters * len(self.kernel_sizes)
        p["W_out"] = rng.randn(H, V) * math.sqrt(2.0 / H)
        p["b_out"] = np.zeros(V)
        self._params = p

    # ============================================================
    # 前向
    # ============================================================
    def _forward(self, X: np.ndarray, training: bool = False):
        """返回 (logits, cache)。X: (B, window)"""
        p = self._params
        E = p["E"][X]                      # (B, L, d)
        B, L, d = E.shape

        pooled_list = []
        cache: Dict[str, Any] = {"X": X, "E": E, "convs": {}}
        for h in self.kernel_sizes:
            if L - h + 1 <= 0:
                continue
            # 滑窗展平：(B, L-h+1, h*d)
            win = np.zeros((B, L - h + 1, h * d))
            for j in range(h):
                win[:, :, j * d:(j + 1) * d] = E[:, j:j + (L - h + 1), :]
            win_flat = win.reshape(-1, h * d)                    # (B*(L-h+1), h*d)
            W = p[f"W{h}"].reshape(self.n_filters, h * d)        # (F, h*d)
            conv = win_flat @ W.T + p[f"b{h}"]                   # (B*(L-h+1), F)
            conv = conv.reshape(B, L - h + 1, self.n_filters)    # (B, T, F)
            relu = np.maximum(conv, 0.0)
            pooled = relu.max(axis=1)                            # (B, F)
            argmax = relu.argmax(axis=1)
            pooled_list.append(pooled)
            cache["convs"][h] = {"win_flat": win_flat, "relu": relu,
                                 "argmax": argmax, "T": L - h + 1}

        feat = np.concatenate(pooled_list, axis=1) if pooled_list else np.zeros((B, 0))

        if training and self.dropout > 0:
            mask = (np.random.RandomState(self._rng.randint(0, 1 << 30))
                    .rand(*feat.shape) >= self.dropout).astype(float)
            feat = feat * mask / (1.0 - self.dropout)
        else:
            mask = None
        cache["mask"] = mask
        cache["feat"] = feat

        logits = feat @ p["W_out"] + p["b_out"]                  # (B, V)
        return logits, cache

    def _softmax(self, logits: np.ndarray) -> np.ndarray:
        z = logits - logits.max(axis=-1, keepdims=True)
        e = np.exp(z)
        return e / e.sum(axis=-1, keepdims=True)

    # ============================================================
    # 反向
    # ============================================================
    def _backward(self, dlogits: np.ndarray, cache: Dict[str, Any],
                  grads: Dict[str, Any]):
        p = self._params
        X, E = cache["X"], cache["E"]
        B, L, d = E.shape
        feat, mask = cache["feat"], cache["mask"]

        grads["W_out"] += feat.T @ dlogits
        grads["b_out"] += dlogits.sum(axis=0)
        dfeat = dlogits @ p["W_out"].T                            # (B, H)
        if mask is not None:
            dfeat = dfeat * mask / (1.0 - self.dropout)

        dE = np.zeros_like(E)
        off = 0
        for h in self.kernel_sizes:
            if h not in cache["convs"]:
                continue
            c = cache["convs"][h]
            T, F = c["T"], self.n_filters
            dpool = dfeat[:, off:off + F]                        # (B, F)
            off += F

            # max-over-time 反向：只有 argmax 位置有梯度，且需过 ReLU 掩码
            dconv = np.zeros((B, T, F))
            bi = np.arange(B)
            dconv[bi[:, None], c["argmax"], np.arange(F)[None, :]] = dpool
            dconv = dconv * (c["relu"] > 0)

            dconv_flat = dconv.reshape(-1, F)                    # (B*T, F)
            grads[f"W{h}"] += (dconv_flat.T @ c["win_flat"]).reshape(F, h, d)
            grads[f"b{h}"] += dconv_flat.sum(axis=0)

            dwin_flat = dconv_flat @ p[f"W{h}"].reshape(F, h * d)  # (B*T, h*d)
            dwin = dwin_flat.reshape(B, T, h * d)
            # 各偏移 j 的切片就地累加，重叠位置自然叠加（等价于滑窗的梯度散射）
            for j in range(h):
                dE[:, j:j + T, :] += dwin[:, :, j * d:(j + 1) * d]

        np.add.at(grads["E"], X.reshape(-1), dE.reshape(-1, d))

    # ============================================================
    # 训练
    # ============================================================
    def fit(self, texts: List[str], epochs: int = 8, batch_size: int = 64,
            lr: Optional[float] = None, verbose: bool = False,
            holdout_texts: Optional[List[str]] = None,
            conditions: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        """训练。返回训练曲线（留出的 perplexity 用于观察过拟合）。

        Args:
            conditions: 条件前缀（问题）。传入即训练**条件**语言模型 ——
                做候选重排序（P(回答|问题)）时**必须**传入：否则训练与推理
                的 context 分布不一致，打分会失效（实测 top-1 仅 5%）。
        """
        vocab_src = list(texts)
        if conditions:
            vocab_src += [c for c in conditions if c]
        if not self._itos:
            self.build_vocab(vocab_src)
        self._init_params()
        # ⚠️ 必须在训练循环**之前**置位：否则每轮的留出 perplexity 会因
        # log_prob 走「未训练」分支而一律返回 LOG_FLOOR，
        # 结果是 exp(20)≈4.85e8 这种荒谬数字（实测踩到过）。
        self._trained = True
        lr = self.lr if lr is None else lr

        X, y = self.build_samples(texts, conditions)
        n = len(X)
        history: List[Dict[str, float]] = []

        for ep in range(epochs):
            perm = np.random.RandomState(self.seed + ep).permutation(n)
            total_loss = 0.0
            for start in range(0, n, batch_size):
                idx = perm[start:start + batch_size]
                xb, yb = X[idx], y[idx]

                grads = {k: np.zeros_like(v) for k, v in self._params.items()}
                logits, cache = self._forward(xb, training=True)
                probs = self._softmax(logits)
                B = len(xb)
                total_loss += -np.log(np.maximum(probs[np.arange(B), yb], 1e-12)).sum()

                dlogits = probs.copy()
                dlogits[np.arange(B), yb] -= 1.0
                dlogits /= B
                self._backward(dlogits, cache, grads)

                for k in self._params:
                    self._params[k] -= lr * grads[k]

            rec: Dict[str, float] = {
                "epoch": ep + 1,
                "loss": total_loss / max(n, 1),
            }
            if holdout_texts:
                from .eval.metrics import perplexity as _pp
                rec["holdout_perplexity"] = _pp(self, holdout_texts)
            history.append(rec)
            if verbose:
                extra = f"  留出 PP={rec['holdout_perplexity']:.2f}" \
                    if "holdout_perplexity" in rec else ""
                print(f"  epoch {ep + 1}/{epochs}  loss={rec['loss']:.4f}{extra}")

        self._trained = True
        return {"history": history, "samples": n, "vocab": self.vocab_size}

    # ============================================================
    # ai.eval 评估协议（与 MarkovChain 一致）
    # ============================================================
    def _probs_for_context(self, context: Sequence[str]) -> Optional[np.ndarray]:
        ids = self._encode(list(context or []))
        if len(ids) < self.window:
            ids = [PAD_ID] * (self.window - len(ids)) + ids
        else:
            ids = ids[-self.window:]
        X = np.array([ids], dtype=np.int64)
        logits, _ = self._forward(X, training=False)
        return self._softmax(logits)[0]

    def log_prob(self, context: Sequence[str], token: str) -> float:
        if not self._trained:
            return LOG_FLOOR
        probs = self._probs_for_context(context)
        i = self._stoi.get(self._norm(token))
        if i is None:
            return LOG_FLOOR
        return float(math.log(max(probs[i], 1e-12)))

    def prob(self, context: Sequence[str], token: str) -> float:
        lp = self.log_prob(context, token)
        return math.exp(lp) if lp > LOG_FLOOR else 0.0

    def top_k(self, context: Sequence[str], k: int = 1) -> List[Tuple[str, float]]:
        if not self._trained:
            return []
        probs = self._probs_for_context(context)
        idx = np.argsort(-probs)[:k]
        return [(self._itos[i], float(probs[i])) for i in idx]

    def perplexity(self, texts: List[str]) -> float:
        from .eval.metrics import perplexity as _pp
        return _pp(self, texts)

    def sequence_log_prob(self, tokens: Sequence[str]) -> float:
        """整段序列的对数似然（自动补 BOS）—— 与 MarkovChain 同接口。

        供 `confidence()` 类的质量度量使用；两侧必须同口径，
        否则马尔科夫与神经网络的置信度无法放在一起比较。
        """
        if not self._trained or not tokens:
            return LOG_FLOOR * max(len(tokens), 1)
        toks = [BOS] + list(tokens)
        total = 0.0
        for i in range(1, len(toks)):
            total += self.log_prob(toks[:i], toks[i])
        return total

    def score_candidates(self, question: str, candidates: Sequence[str],
                         length_normalize: bool = True) -> List[float]:
        """条件似然打分：Σ log P(候选_i | 问题 + 候选_{<i})。

        这是把 CNN 用回它**被证明更强**的场景的关键 —— P2 的对照显示，
        TextCNN 在 teacher-forcing（用真实前驱预测下一个 token）上比 n-gram 高
        9.14pp；而自由生成时它会输给「精确记忆原句」的马尔科夫。
        打分器正好只需要前者：候选是给定的，模型只需判断哪个更贴切。

        与语言模型打分的经典做法一致（用 P(回复|问题) 给候选重排序），
        且**不需要新模型** —— 现有的 context→next 结构天然可用。

        Args:
            question: 用户输入（作为条件前缀）。
            candidates: 候选回复列表。
            length_normalize: 按 token 数取平均，避免长候选因累加而吃亏。

        Returns:
            每个候选的得分（越大越好；未训练时全为 -inf）。
        """
        if not self._trained:
            return [float("-inf")] * len(candidates)

        # 必须与条件训练时的序列构造一致：`[BOS] 问题 SEP 回答`
        q_tokens = [BOS] + tokenize(question or "")
        if question:
            q_tokens.append(SEP)
        scores: List[float] = []
        for cand in candidates:
            c_tokens = tokenize(cand or "")
            if not c_tokens:
                scores.append(float("-inf"))
                continue
            ctx = list(q_tokens)
            total = 0.0
            for t in c_tokens:
                total += self.log_prob(ctx, t)
                ctx.append(t)
            scores.append(total / len(c_tokens) if length_normalize else total)
        return scores

    def confidence(self, text: str) -> float:
        """相对均匀基线的归一化增益 ∈ [0,1]（与 MarkovChain.confidence 同口径）。"""
        if not self._trained or not text:
            return 0.0
        toks = tokenize(text)
        if not toks:
            return 0.0
        mlp = self.sequence_log_prob(toks) / len(toks)
        V = max(self.vocab_size, 2)
        gain = (mlp + math.log(V)) / math.log(V)
        return max(0.0, min(1.0, gain))

    # ============================================================
    # 生成（自回归采样，供对话链路使用）
    # ============================================================
    def sample(self, seed_prefix: Optional[Sequence[str]] = None,
               max_length: int = 60, temperature: float = 0.8) -> str:
        """从种子开始逐 token 自回归采样。

        每步都要跑一次前向（词表规模 V 上的 softmax），因此比查表式的
        马尔科夫链慢约一个量级 —— 这是接入链路时必须知道的成本。

        UNK 与 PAD **只推进上下文、不写入输出**，与 MarkovChain.sample 同策略：
        否则会在句子中间留下空洞（P0 实测过的碎片化问题）。
        """
        if not self._trained:
            return ""
        ctx: List[str] = list(seed_prefix or [])
        out: List[str] = []
        rng = random.Random(self._rng.randint(0, 1 << 30))

        for _ in range(max_length):
            probs = self._probs_for_context(ctx)
            if probs is None:
                break
            w = probs ** (1.0 / temperature) if temperature > 0 else probs
            total = float(w.sum())
            if total <= 0:
                break
            r = rng.random() * total
            acc = 0.0
            pick = int(len(w) - 1)
            for i, p in enumerate(w):
                acc += float(p)
                if r <= acc:
                    pick = i
                    break
            tok = self._itos[pick]
            if tok == EOS:
                break
            if tok not in (UNK, PAD):
                out.append(tok)
            ctx.append(tok)
            # 上下文只保留最近若干 token，避免无限增长拖慢每步前向
            if len(ctx) > self.window * 3:
                ctx = ctx[-self.window * 3:]
            if tok in ('。', '！', '？', '!', '?', '.') and rng.random() < 0.3:
                break

        return detokenize(out)

    def generate_variations(self, seed_prefix: Sequence[str], count: int = 3,
                            temperature: float = 0.8,
                            max_length: int = 60) -> List[str]:
        """采样多个候选（对话回复多样性）。"""
        seen: Set[str] = set()
        out: List[str] = []
        for _ in range(count * 2):
            s = self.sample(seed_prefix, max_length=max_length,
                            temperature=temperature)
            if s and s not in seen:
                seen.add(s)
                out.append(s)
            if len(out) >= count:
                break
        return out

    # ============================================================
    # 意图分类（复用同一骨干，接一个分类头之外的用法）
    # ============================================================
    def predict_next(self, context: Sequence[str], k: int = 3) -> List[Tuple[str, float]]:
        """预测下一个 token（供生成/调试）。"""
        return self.top_k(context, k)

    # ============================================================
    # 持久化：权重导出（为「零依赖运行期」铺路）
    # ============================================================
    def save(self, filepath: str):
        payload = {
            "format": "easy-ai-textcnn/1",
            "window": self.window, "embed_dim": self.embed_dim,
            "n_filters": self.n_filters, "kernel_sizes": list(self.kernel_sizes),
            "dropout": self.dropout, "unk_cutoff": self.unk_cutoff,
            "itos": self._itos, "kept": sorted(self._kept),
            "params": {k: v.tolist() for k, v in self._params.items()},
        }
        Path(filepath).write_text(json.dumps(payload, ensure_ascii=False),
                                  encoding="utf-8")

    @classmethod
    def load(cls, filepath: str) -> "TextCNN":
        d = json.loads(Path(filepath).read_text(encoding="utf-8"))
        m = cls(window=d["window"], embed_dim=d["embed_dim"],
                n_filters=d["n_filters"], kernel_sizes=d["kernel_sizes"],
                dropout=d["dropout"], unk_cutoff=d["unk_cutoff"])
        m._itos = d["itos"]
        m._stoi = {w: i for i, w in enumerate(m._itos)}
        m._kept = set(d.get("kept", m._itos))
        m._params = {k: np.array(v) for k, v in d["params"].items()}
        m._trained = bool(m._params)
        return m

    @property
    def is_trained(self) -> bool:
        return self._trained

    def __repr__(self):
        return (f"<TextCNN window={self.window} dim={self.embed_dim} "
                f"filters={self.n_filters}x{self.kernel_sizes} "
                f"V={self.vocab_size} trained={self._trained}>")
