"""
马尔科夫链语言模型：n-gram 概率模型 + 平滑 + 可评估接口。

本轮（P0）修复的四个实测缺陷（详见 docs/DEEPEN_P0.md）：
- D4 伪置信度：旧版 `_calculate_overlap` 用 Jaccard(输入, 生成文本) 冒充置信度，
  与生成质量无关且恒偏高。现改为**相对均匀基线的归一化增益**（口径同 weiqi_lab）。
- D6 无平滑：旧版只做逐级回退，未见 n-gram 概率为 0。现支持 add-k 与
  **插值式 Kneser-Ney**（用延续概率替代原始频次，是 n-gram 平滑的实用上限）。
- D8 死代码 / 性能炸弹：旧版 `_build_keyword_index` 是空实现，
  `_build_corpus_keywords` 是 O(语料×状态) 双重循环。现改为字符 bigram 倒排索引。
- D9 语义错位：旧版以「用户输入」为 seed 续写，产出的是用户句子的续写而非回复。
  现**用户语料与 AI 语料分离建模**，回复从 AI 侧链生成。

参考：
- Kneser-Ney：低阶分布用「延续概率」（一个词出现在多少种不同上下文中）而非原始频次。
- weiqi_lab docs/TIER3_LEARNING.md §2.6：评估先于优化，留出集 + 均匀基线 + 相对增益。
"""

from __future__ import annotations

import json
import logging
import math
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..eval.tokenize import tokenize, detokenize, BOS, EOS, UNK
from ..eval.metrics import LOG_FLOOR
from .base import BaseMatcher, MatchResult
from .registry import register_matcher
from .retrieval import RetrievalIndex

# Kneser-Ney 折扣系数（经验值 0.75，Chen & Goodman 扫描结果的常用档）
KN_DISCOUNT = 0.75

# 语料降级等「不该静默」的事件走这里（见 MarkovMatcher._load_corpus 的教训）
_log = logging.getLogger(__name__)


class MarkovChain:
    """N-gram 马尔科夫链语言模型。

    相比旧版的三点实质变化：
    1. 概率是**平滑后的真实概率**（`log_prob`），不再是「计数列表里抽样」；
    2. 暴露 `perplexity` / `top_k` / `log_prob`，可被 `ai.eval` 直接评估；
    3. 支持 `save` / `load`（为 P2 的蒸馏与随仓分发铺路）。
    """

    SUPPORTED_SMOOTHING = ("none", "add_k", "kneser_ney")

    def __init__(self, n: int = 2, smoothing: str = "kneser_ney", k: float = 0.1,
                 unk_cutoff: int = 1):
        """
        Args:
            n: n-gram 阶数（1-5，推荐 2-4）。
            smoothing: 平滑方式 —— "none"（无，仅回退）/ "add_k" / "kneser_ney"。
            k: add-k 平滑的 k 值（"add_k" 时生效）。
            unk_cutoff: 训练集中出现次数 <= 该值的 token 一律折叠为 `<unk>`。
                0 = 不启用（此时未见词概率归零，perplexity 会被 LOG_FLOOR 主导）。

        ⚠️ unk_cutoff 为什么默认开：本项目语料极小（数千 token），留出集 OOV 率
        实测 28%+。不折叠的话，perplexity 反映的几乎全是「有多少词没见过」，
        而不是模型的建模质量 —— 平滑方式之间也就没法公平比较。
        """
        if n < 1:
            raise ValueError(f"n 必须 >= 1，当前值：{n}")
        if smoothing not in self.SUPPORTED_SMOOTHING:
            raise ValueError(f"不支持的平滑方式：{smoothing}，可选 {self.SUPPORTED_SMOOTHING}")

        self.n = max(1, n)
        self.smoothing = smoothing
        self.k = float(k)
        self.unk_cutoff = int(unk_cutoff)
        # 保留词表：频次 > cutoff 的 token（UNK 永远在表内，作为未见词兜底）
        self._kept: Set[str] = set()

        # level -> prefix -> {next_token: count}
        self._counts: Dict[int, Dict[Tuple[str, ...], Dict[str, int]]] = {}
        # level -> prefix -> 总计数
        self._prefix_totals: Dict[int, Dict[Tuple[str, ...], int]] = {}
        # level -> token -> 该 token 作为后继出现的「不同 prefix 数」（KN 延续计数）
        self._continuation: Dict[int, Dict[str, int]] = {}
        # level -> 延续计数总和（用于归一）
        self._continuation_totals: Dict[int, int] = {}
        self._vocab: Set[str] = set()
        self._trained = False

    # ============================================================
    # 训练
    # ============================================================
    def train(self, texts: List[str], tokenize_text: bool = True):
        """用文本列表训练（向后兼容旧签名 `train(texts, tokenize=True)`）。"""
        seqs: List[List[str]] = []
        for text in texts:
            if not text or not text.strip():
                continue
            toks = tokenize(text) if tokenize_text else text.split()
            if len(toks) < 1:
                continue
            seqs.append([BOS] + toks + [EOS])

        if not seqs:
            return

        self._counts.clear()
        self._prefix_totals.clear()
        self._continuation.clear()
        self._continuation_totals.clear()
        self._vocab.clear()
        self._vocab.update((BOS, EOS, UNK))

        # UNK 折叠：低频词（含留出集里才会出现的新词）统一映射到 <unk>，
        # 使概率质量集中于「可学的转移」，而不是被海量 hapax 稀释。
        if self.unk_cutoff > 0:
            freq: Dict[str, int] = defaultdict(int)
            for toks in seqs:
                for t in toks:
                    freq[t] += 1
            self._kept = {t for t, c in freq.items() if c > self.unk_cutoff}
            self._kept.update((BOS, EOS))
            seqs = [[t if t in self._kept else UNK for t in toks] for toks in seqs]
        else:
            self._kept = set()
            for toks in seqs:
                self._kept.update(toks)
            self._kept.update((BOS, EOS))

        for level in range(1, self.n + 1):
            counts: Dict[Tuple[str, ...], Dict[str, int]] = defaultdict(lambda: defaultdict(int))
            totals: Dict[Tuple[str, ...], int] = defaultdict(int)
            cont: Dict[str, int] = defaultdict(int)

            for toks in seqs:
                for t in toks:
                    self._vocab.add(t)
                # level 阶：prefix 长度 level-1，预测第 level 个 token
                for i in range(len(toks) - level + 1):
                    prefix = tuple(toks[i:i + level - 1]) if level > 1 else ()
                    nxt = toks[i + level - 1]
                    counts[prefix][nxt] += 1
                    totals[prefix] += 1

            # 延续计数：一个 token 出现在多少种不同 prefix 之后
            for prefix, dist in counts.items():
                for nxt in dist:
                    cont[nxt] += 1

            self._counts[level] = {p: dict(d) for p, d in counts.items()}
            self._prefix_totals[level] = dict(totals)
            self._continuation[level] = dict(cont)
            self._continuation_totals[level] = sum(cont.values())

        self._trained = True

    def train_pairs(self, pairs: Sequence[Tuple[str, str]]):
        """用问答对训练 —— 只把「答」作为语言建模语料。

        这是修复 D9 的关键之一：用户语料与 AI 语料**不能混在一起训**，
        否则模型学到的转移是「用户话 → AI 话 → 用户话」的串烧分布。
        """
        self.train([a for _, a in pairs if a])

    # ============================================================
    # 概率接口（ai.eval 的评估协议）
    # ============================================================
    def log_prob(self, context: Sequence[str], token: str) -> float:
        """给定上下文，返回 token 的平滑后对数概率（自然对数）。"""
        if not self._trained:
            return LOG_FLOOR
        try:
            p = self.prob(context, token)
        except (KeyError, ZeroDivisionError):
            return LOG_FLOOR
        if p <= 0.0 or math.isnan(p):
            return LOG_FLOOR
        return math.log(p)

    def _norm(self, token: str) -> str:
        """把未登录 token 折叠为 <unk>（UNK 自身始终合法）。"""
        if token == UNK or not self._kept or token in self._kept:
            return token if token in self._vocab else UNK
        return UNK

    def prob(self, context: Sequence[str], token: str) -> float:
        """平滑后的概率 P(token | context)（未登录词按 <unk> 计）。"""
        if not self._trained:
            return 0.0
        tok = self._norm(token)
        ctx = [self._norm(c) for c in (context or [])]
        if self.smoothing == "kneser_ney":
            p = self._kn_prob(ctx, tok, self.n)
        elif self.smoothing == "add_k":
            p = self._addk_prob(ctx, tok)
        else:
            p = self._mle_with_backoff(ctx, tok)
        return p if p > 0.0 else 1.0 / max(len(self._vocab), 1)

    def _addk_prob(self, ctx: List[str], token: str) -> float:
        """Add-k 平滑：P = (c + k) / (N + k·V)，逐级回退到低阶。"""
        V = max(len(self._vocab), 1)
        for level in range(self.n, 0, -1):
            prefix = self._tail(ctx, level - 1)
            dist = self._counts.get(level, {}).get(prefix)
            if not dist:
                continue
            total = self._prefix_totals[level].get(prefix, 0)
            return (dist.get(token, 0) + self.k) / (total + self.k * V)
        # 完全没见过：退回均匀
        return 1.0 / V

    def _mle_with_backoff(self, ctx: List[str], token: str) -> float:
        """无平滑的 MLE + 逐级回退（保留旧行为，作为对照基线）。"""
        for level in range(self.n, 0, -1):
            prefix = self._tail(ctx, level - 1)
            dist = self._counts.get(level, {}).get(prefix)
            total = self._prefix_totals.get(level, {}).get(prefix, 0)
            if dist and total > 0 and token in dist:
                return dist[token] / total
        return 0.0

    def _kn_prob(self, ctx: List[str], token: str, level: int) -> float:
        """插值式 Kneser-Ney（递归）。

        P_KN(w|ctx) = max(c(ctx,w) - D, 0)/N(ctx)
                    + [D·|{w': c(ctx,w')>0}| / N(ctx)] · P_KN(w | ctx 去掉最老 token)

        最低阶退化成延续概率：P_KN(w) = |{ctx: c(ctx,w)>0}| / Σ_{w'} |{ctx: c(ctx,w')>0}|
        —— 这正是 KN 的核心：低阶用「出现在多少种上下文」而非「出现多少次」。
        """
        if level <= 1:
            cont = self._continuation.get(2) or self._continuation.get(1) or {}
            tot = self._continuation_totals.get(2) or self._continuation_totals.get(1) or 0
            if tot <= 0:
                return 1.0 / max(len(self._vocab), 1)
            return (cont.get(token, 0) + self.k) / (tot + self.k * len(self._vocab))

        prefix = self._tail(ctx, level - 1)
        dist = self._counts.get(level, {}).get(prefix)
        total = self._prefix_totals.get(level, {}).get(prefix, 0)

        if not dist or total <= 0:
            # 该阶无此 prefix → 整阶让位给低阶
            return self._kn_prob(ctx, token, level - 1)

        lower = self._kn_prob(ctx, token, level - 1)
        D = KN_DISCOUNT
        first = max(dist.get(token, 0) - D, 0.0) / total
        num_types = len(dist)
        lam = (D * num_types) / total
        return first + lam * lower

    @staticmethod
    def _tail(ctx: List[str], length: int) -> Tuple[str, ...]:
        """取上下文最后 length 个 token 作为 prefix；不足则全取。"""
        if length <= 0:
            return ()
        return tuple(ctx[-length:]) if len(ctx) >= length else tuple(ctx)

    def top_k(self, context: Sequence[str], k: int = 1) -> List[Tuple[str, float]]:
        """概率最高的前 k 个后继 token。"""
        if not self._trained:
            return []
        ctx = [self._norm(c) for c in (context or [])]
        # 候选集：该 n 阶 prefix 下见过的 token + 低阶兜底
        cands: Set[str] = set()
        for level in range(self.n, 0, -1):
            dist = self._counts.get(level, {}).get(self._tail(ctx, level - 1))
            if dist:
                cands.update(dist.keys())
                if len(cands) >= 64:
                    break
        scored = [(w, self.prob(ctx, w)) for w in cands]
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:k]

    def sequence_log_prob(self, tokens: Sequence[str]) -> float:
        """整段序列的对数似然（内部自动加 BOS）。"""
        if not self._trained or not tokens:
            return LOG_FLOOR * max(len(tokens), 1)
        toks = [BOS] + list(tokens)
        total = 0.0
        for i in range(1, len(toks)):
            total += self.log_prob(toks[:i], toks[i])
        return total

    def perplexity(self, texts: List[str]) -> float:
        """困惑度（自身实现，便于不依赖 ai.eval 时也能用）。"""
        from ..eval.metrics import perplexity as _pp
        return _pp(self, texts)

    # ============================================================
    # 置信度（D4 修复：真·基于模型概率，而非字符重叠）
    # ============================================================
    def confidence(self, text: str) -> float:
        """相对均匀基线的归一化信息增益 ∈ [0,1]。

        - 0   = 模型在这段文本上跟瞎猜（均匀分布）一样好；
        - 1   = 模型给出确定性预测（平均概率 1）；
        - 口径与 weiqi_lab 的「相对均匀」一致，故不同语料/模型间可直接比较。

        旧版用 Jaccard(输入,生成文本) 冒充置信度，与生成质量无关且恒偏高 —— 已废弃。
        """
        if not self._trained or not text:
            return 0.0
        toks = tokenize(text)
        if not toks:
            return 0.0
        mlp = self.sequence_log_prob(toks) / len(toks)
        V = max(len(self._vocab), 2)
        lp_uniform = -math.log(V)
        # 增益 = (实测平均对数概率 - 瞎猜) / (完美 - 瞎猜)
        gain = (mlp - lp_uniform) / (0.0 - lp_uniform)
        return max(0.0, min(1.0, gain))

    # ============================================================
    # 生成（向后兼容）
    # ============================================================
    def sample(self, start: Optional[str] = None, max_length: int = 50,
               temperature: float = 1.0, seed_prefix: Optional[List[str]] = None) -> str:
        """从模型采样生成文本。概率来自平滑后的分布，而非原始计数。"""
        if not self._trained:
            return ""

        current: List[str] = []
        if seed_prefix:
            current = list(seed_prefix)[-(self.n - 1):] if self.n > 1 else []
        elif start:
            st = tokenize(start)
            current = st[-(self.n - 1):] if (self.n > 1 and st) else list(st)

        generated: List[str] = []
        if start and not seed_prefix:
            generated.extend(tokenize(start))

        for _ in range(max_length):
            nxt = self._predict(current, temperature)
            if nxt is None or nxt == EOS:
                break
            # UNK 保留在上下文里以维持 n-gram 连贯，但**不写进输出** ——
            # 否则 detokenize 把它删掉后会在句子中间留下空洞
            # （实测表现为「：，可能通往人类智能降落？」这类碎片）。
            if nxt != UNK:
                generated.append(nxt)
            current = (current + [nxt])[-(max(self.n - 1, 1)):]
            if nxt in ('。', '！', '？', '!', '?', '.') and random.random() < 0.3:
                break

        return detokenize(generated)

    def _predict(self, prefix: Sequence[str], temperature: float = 1.0) -> Optional[str]:
        """按平滑后的概率分布采样下一个 token。"""
        ctx = [self._norm(c) for c in (prefix or [])]
        cands: Set[str] = set()
        for level in range(self.n, 0, -1):
            dist = self._counts.get(level, {}).get(self._tail(ctx, level - 1))
            if dist:
                cands.update(dist.keys())
                if len(cands) >= 64:
                    break
        if not cands:
            return None
        weights = [self.prob(ctx, w) for w in cands]
        return self._weighted_sample(list(cands), weights, temperature)

    def _weighted_sample(self, tokens: List[str], weights: List[float],
                         temperature: float = 1.0) -> str:
        """带温度的加权采样（权重已是概率，非计数）。"""
        if not tokens:
            return ""
        if temperature <= 0:
            return tokens[max(range(len(weights)), key=lambda i: weights[i])]

        if temperature != 1.0:
            # T>1 平滑分布（更随机）；T<1 锐化（更确定）
            scaled = [max(w, 1e-12) ** (1.0 / temperature) for w in weights]
        else:
            scaled = [max(w, 1e-12) for w in weights]

        total = sum(scaled)
        if total <= 0:
            return random.choice(tokens)
        r = random.random() * total
        acc = 0.0
        for tok, w in zip(tokens, scaled):
            acc += w
            if r <= acc:
                return tok
        return tokens[-1]

    def generate_variations(self, seed: str, count: int = 5,
                            temperature: float = 0.8, max_length: int = 60) -> List[str]:
        """生成多个变体文本（对话回复多样性）。"""
        out: List[str] = []
        seen: Set[str] = set()
        for _ in range(count * 3):
            txt = self.sample(start=seed, max_length=max_length, temperature=temperature)
            if txt and txt not in seen:
                seen.add(txt)
                out.append(txt)
            if len(out) >= count:
                break
        return out

    def get_transition_probability(self, prefix: Tuple[str, ...], next_token: str) -> float:
        """给定 prefix 下 next_token 的平滑概率（旧接口保留，语义改为平滑概率）。"""
        return self.prob(list(prefix or []), next_token)

    # ============================================================
    # 持久化（P2 蒸馏铺路）
    # ============================================================
    def save(self, filepath: str):
        """导出为 JSON（计数表，非概率表 —— 换平滑方式可重算）。"""
        payload = {
            "format": "easy-ai-markov/1",
            "n": self.n,
            "smoothing": self.smoothing,
            "k": self.k,
            "vocab": sorted(self._vocab),
            "kept": sorted(self._kept),
            "unk_cutoff": self.unk_cutoff,
            "counts": {
                str(lv): {json.dumps(list(p), ensure_ascii=False): d
                          for p, d in dist.items()}
                for lv, dist in self._counts.items()
            },
        }
        Path(filepath).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, filepath: str) -> "MarkovChain":
        """从 JSON 恢复。"""
        data = json.loads(Path(filepath).read_text(encoding="utf-8"))
        m = cls(n=data["n"], smoothing=data.get("smoothing", "add_k"),
                k=data.get("k", 0.1), unk_cutoff=data.get("unk_cutoff", 1))
        m._vocab = set(data.get("vocab", []))
        m._kept = set(data.get("kept", [])) or set(m._vocab)
        m._counts = {}
        m._prefix_totals = {}
        m._continuation = {}
        m._continuation_totals = {}
        for lv_s, dist in data.get("counts", {}).items():
            lv = int(lv_s)
            counts = {}
            totals = {}
            cont: Dict[str, int] = defaultdict(int)
            for p_s, d in dist.items():
                p = tuple(json.loads(p_s))
                counts[p] = d
                totals[p] = sum(d.values())
                for w in d:
                    cont[w] += 1
            m._counts[lv] = counts
            m._prefix_totals[lv] = totals
            m._continuation[lv] = dict(cont)
            m._continuation_totals[lv] = sum(cont.values())
        m._trained = bool(m._counts)
        return m

    # ============================================================
    # 属性
    # ============================================================
    @property
    def vocab(self) -> Set[str]:
        return set(self._vocab)

    @property
    def vocab_size(self) -> int:
        return len(self._vocab)

    @property
    def total_states(self) -> int:
        return sum(len(d) for d in self._counts.values())

    @property
    def is_trained(self) -> bool:
        return self._trained

    def __repr__(self):
        return (f"<MarkovChain n={self.n} smoothing={self.smoothing} "
                f"vocab={self.vocab_size} states={self.total_states} "
                f"trained={self._trained}>")


# ================================================================
# 匹配器
# ================================================================
@register_matcher("markov")
class MarkovMatcher(BaseMatcher):
    """马尔科夫链匹配器：基于语料概率生成回复。

    与旧版的根本区别（D9 修复）：
    - 旧版：把用户输入当 seed，从「用户语料+AI语料混训」的模型里续写 → 产出的是
      **用户句子的续写**，不是回复。
    - 新版：AI 语料单独建模（`_ai_chain`）；输入只用于**检索**最相关的历史回复，
      取该回复的开头作 seed，再从 **AI 链** 生成 → 产出的是**回复**。

    置信度（D4 修复）：`生成序列的相对均匀基线增益 × 检索相关性`，
    不再用 Jaccard(输入, 生成文本) 那种与质量无关的量。
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "MarkovMatcher"
        cfg = config or {}
        self.priority = cfg.get("priority", 30)
        self.n_gram = cfg.get("n_gram", 3)
        self.temperature = cfg.get("temperature", 0.8)
        self.max_length = cfg.get("max_length", 80)
        # 生成候选数：采样多次择优，抵御马尔科夫采样的随机抖动
        self.n_candidates = int(cfg.get("n_candidates", 3))
        smoothing = cfg.get("smoothing", "kneser_ney")

        self._ai_chain = MarkovChain(n=self.n_gram, smoothing=smoothing,
                                     k=cfg.get("k", 0.1),
                                     unk_cutoff=cfg.get("unk_cutoff", 1))
        # 检索索引（与 NeuralMatcher 共用同一实现，见 ai/matchers/retrieval.py）
        self._index = RetrievalIndex()
        self._questions: List[str] = []
        self._answers: List[str] = []

        # 启动时预加载真实语料（配置驱动）
        corpus_spec = cfg.get("corpus")
        if corpus_spec:
            self._load_corpus(corpus_spec)

    def _load_corpus(self, spec: str):
        """按配置加载语料。

        `corpus: "auto"` → 项目内真实事件流（data/training_log.json、
        ai_training.json、scenes/）。这是 P0 的核心接入：链上的马尔科夫
        从此吃真实问答对，而不是规则库的模板串烧。

        语料是**增强项**：加载失败只降级（惰性 build_from_rules），
        绝不能让 AICore() 启动失败 —— 零配置启动是既有契约。

        ⚠️ 但降级必须**留痕**：早先这里写的是 `except Exception: pass`，
        结果把 `QAPair 不能解包` 的真 bug 吞得无声无息（表现为「模型永远
        没训练」却没有任何线索）。静默兜底等于把故障推迟到最贵的时刻。
        """
        try:
            from ..eval.corpus import Corpus
            if spec == "auto":
                c = Corpus.from_easy_ai()
            else:
                c = Corpus.from_easy_ai(spec)
            if c.pairs:
                self.build_from_pairs(c.pairs)
        except Exception as e:
            _log.warning("马尔科夫语料加载失败（%s），降级为规则库惰性训练：%s",
                         spec, e)

    # ---------- 训练 ----------
    def build_from_pairs(self, pairs: Sequence[Any]):
        """用问答对训练：AI 语料建模 + 用户侧检索索引。

        同时接受两种形态（避免调用方被迫转换）：
        - `("问", "答")` 元组/列表序列
        - `ai.eval.QAPair` 对象（`Corpus.pairs` 的原生形态）
        """
        qs: List[str] = []
        ans: List[str] = []
        for p in pairs or ():
            if isinstance(p, (tuple, list)):
                q = p[0] if len(p) > 0 else ""
                a = p[1] if len(p) > 1 else ""
            else:
                q = getattr(p, "question", "")
                a = getattr(p, "answer", "")
            if q and a:
                qs.append(q)
                ans.append(a)
        self._questions = qs
        self._answers = ans
        if self._answers:
            self._ai_chain.train(self._answers)
        self._build_index(self._questions)

    def build_from_rules(self, rules: List[Dict[str, Any]]):
        """从规则库构建（向后兼容）。

        注意：这是**质量最差**的语料来源（pattern 与 response 都是模板串），
        仅用于零配置时的兜底。有真实问答对时应优先 `build_from_pairs`。
        """
        qa: List[Tuple[str, str]] = []
        for rule in rules:
            pattern = rule.get("pattern", "")
            if not pattern or pattern == ".*":
                continue
            q = re.sub(r'[.*+?^$(){}|\[\]\\]', '', pattern).strip()
            for resp in rule.get("responses", []):
                if q and resp:
                    qa.append((q, resp))
        self.build_from_pairs(qa)

    def build_from_texts(self, texts: List[str]):
        """纯文本语料（无问答结构时）—— 只建模，不建检索索引。"""
        self._ai_chain.train(texts)
        self._questions = []
        self._answers = list(texts)
        self._build_index(texts)

    # ---------- 检索索引（与 NeuralMatcher 共用实现）----------
    def _build_index(self, questions: List[str]):
        self._index.build(questions)

    def retrieve(self, text: str, top_n: int = 3) -> List[Tuple[int, float]]:
        """检索与输入最相关的历史问答，返回 [(下标, 相关性)]（0-1 归一）。"""
        return self._index.retrieve(text, top_n)

    # ---------- 匹配 ----------
    def match(self, text: str, rules: List[Dict[str, Any]]) -> Optional[MatchResult]:
        """生成回复：检索相关回复作种子 → 从 AI 链生成 → 按模型概率给置信度。"""
        if not self._ai_chain.is_trained:
            if rules:
                self.build_from_rules(rules)
            else:
                return None
        if not self._ai_chain.is_trained:
            return None

        hits = self.retrieve(text, top_n=1)
        if not hits:
            return None
        idx, relevance = hits[0]

        # 种子：取相关回复的开头若干 token，让生成沿「AI 说话」的分布走
        seed_answer = self._answers[idx] if idx < len(self._answers) else ""
        seed_tokens = tokenize(seed_answer)[:max(2, self.n_gram - 1)]

        # 生成多个候选 + 检索到的原文一起竞争，取模型质量最高者。
        # 为什么要让原文参选：留出集指标（top-1/perplexity）衡量的是逐 token
        # 预测精度，**不等于**生成序列的连贯性 —— 实测出现过「指标上升但
        # 端到端回复变成碎片」的情况。让真实语料原文参与竞争，等于给生成质量
        # 设了一条下限：生成不出更好的，就如实回放语料里真实发生过的回答。
        candidates: List[str] = []
        for _ in range(max(1, self.n_candidates)):
            g = self._ai_chain.sample(
                seed_prefix=seed_tokens,
                max_length=self.max_length,
                temperature=self.temperature,
            )
            if g and len(g) >= 2:
                candidates.append(g)
        if seed_answer:
            candidates.append(seed_answer)
        if not candidates:
            return None

        scored = [(self._ai_chain.confidence(c), c) for c in candidates]
        scored.sort(key=lambda x: (-x[0], len(x[1])))
        quality, generated = scored[0]

        # 置信度 = 生成序列的模型质量 × 检索相关性（D4 修复）
        confidence = quality * max(0.0, min(1.0, relevance))
        # 上限 0.75：马尔科夫是创意兜底，不应压过规则精确匹配（0.95）
        confidence = min(confidence, 0.75)

        return MatchResult(
            reply=generated,
            confidence=confidence,
            source=self.name,
            metadata={
                "n_gram": self.n_gram,
                "smoothing": self._ai_chain.smoothing,
                "temperature": self.temperature,
                "relevance": round(relevance, 4),
                "quality": round(quality, 4),
                "seed_source": "retrieval",
            },
        )

    def generate(self, seed: str, count: int = 3, temperature: Optional[float] = None) -> List[str]:
        """生成多个候选回复（供外部调用）。"""
        if not self._ai_chain.is_trained:
            return []
        return self._ai_chain.generate_variations(
            seed, count=count, temperature=temperature or self.temperature)

    @property
    def model(self) -> MarkovChain:
        return self._ai_chain

    def __repr__(self):
        return (f"<MarkovMatcher n={self.n_gram} smoothing={self._ai_chain.smoothing} "
                f"priority={self.priority} trained={self._ai_chain.is_trained} "
                f"pairs={len(self._questions)}>")
