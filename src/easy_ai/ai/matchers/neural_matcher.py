"""
神经网络匹配器 —— 把 P2 的 TextCNN 接进对话链路。

设计要点：
1. **离线训练 / 运行期加载**：TextCNN 训练需数秒（马尔科夫只要毫秒），
   直接放进启动路径会拖慢 `AICore()` 的零参数启动。所以默认走
   「权重文件存在 → 加载（毫秒级）；不存在且配了 corpus → 现场训练一次」。
2. **与马尔科夫同口径竞争**：置信度 = 生成序列的模型质量 × 检索相关性，
   质量用「相对均匀基线的归一化增益」，与 MarkovChain.confidence 完全同源，
   因此两者的置信度可以直接放在一起比大小（这是公平竞争的前提）。
3. **原文保底**：与马尔科夫匹配器一样，检索到的真实语料原文参与候选竞争。
   留出集指标（top-1/perplexity）衡量的是逐 token 预测精度，不等于生成
   序列的连贯性 —— 实测出现过「指标涨了但回复变碎片」的情况。

成本提醒：TextCNN 生成是**逐步自回归**，每个 token 都要跑一次全词表 softmax，
因此单条回复的生成耗时比马尔科夫高约一个数量级（数十毫秒级）。
默认 `enabled: false`，按需开启。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..eval.tokenize import tokenize
from ..textcnn import TextCNN
from .base import BaseMatcher, MatchResult
from .registry import register_matcher
from .retrieval import RetrievalIndex

_log = logging.getLogger(__name__)

# 权重默认位置（相对项目根）。按用途分开 —— 无条件模型用于自由生成，
# 条件模型 P(回答|问题) 用于重排序；两者训练的 context 构造不同，
# 混用会让打分失效（实测 top-1 只有 5%，条件化后升到 40%）。
DEFAULT_WEIGHTS = "data/textcnn_weights.json"
DEFAULT_WEIGHTS_RERANK = "data/textcnn_rerank_weights.json"


@register_matcher("neural")
class NeuralMatcher(BaseMatcher):
    """基于 TextCNN 的生成式匹配器。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "NeuralMatcher"
        cfg = config or {}
        self.priority = cfg.get("priority", 35)
        self.temperature = cfg.get("temperature", 0.8)
        self.max_length = int(cfg.get("max_length", 60))
        self.n_candidates = int(cfg.get("n_candidates", 3))

        # 工作模式：
        #   generate — 自回归生成候选（P2 默认；实测在似然口径下不敌记忆型马尔科夫）
        #   rerank   — 不生成，只给检索到的真实语料候选打分排序
        #              这是 CNN 的正确定位：它强在 teacher-forcing 的泛化评估。
        self.mode = cfg.get("mode", "rerank")
        # rerank 候选池大小（从检索结果里取前 N 条原文）
        self.rerank_pool = int(cfg.get("rerank_pool", 5))
        # 打分器：cnn（条件似然，默认）/ jaccard（朴素词汇匹配）/ hybrid（两者加权）
        # 实测（tools/eval_rerank.py，留出 20 条）：jaccard 60.00% > cnn 40.00%，
        # 但样本量小、不足以定论；故做成可配置，让实测数据决定用哪个。
        self.scorer = cfg.get("scorer", "cnn")
        self.hybrid_alpha = float(cfg.get("hybrid_alpha", 0.5))

        self._index = RetrievalIndex()
        self._questions: List[str] = []
        self._answers: List[str] = []

        cnn_cfg = {
            "window": int(cfg.get("window", 4)),
            "embed_dim": int(cfg.get("embed_dim", 32)),
            "n_filters": int(cfg.get("n_filters", 32)),
            "kernel_sizes": tuple(cfg.get("kernel_sizes", (2, 3, 4))),
            "lr": float(cfg.get("lr", 0.05)),
            "unk_cutoff": int(cfg.get("unk_cutoff", 1)),
            "seed": int(cfg.get("seed", 0)),
        }
        self._epochs = int(cfg.get("epochs", 20))
        self._batch = int(cfg.get("batch_size", 64))
        self._cnn = TextCNN(**cnn_cfg)
        self._weights_loaded = False
        self._ready = False

        # ① 优先加载已有权重（毫秒级）—— 这只会恢复「怎么说话」的语言模型
        weights = cfg.get("weights", "auto")
        if weights:
            path = self._resolve_weights(weights, rerank=(self.mode == "rerank"))
            if path and path.exists():
                try:
                    self._cnn = TextCNN.load(str(path))
                    self._weights_loaded = True
                except Exception as e:
                    _log.warning("TextCNN 权重加载失败（%s）：%s", path, e)

        # ② 检索索引决定「说什么」，与权重无关，**必须单独构建**。
        #    早先只在「无权重」时才建语料，结果加载权重后 pairs=0、match() 恒返回
        #    None，neural 形同虚设（实测所有回复仍落到马尔科夫）。
        if cfg.get("corpus"):
            self._init_from_corpus(cfg.get("corpus"),
                                   need_train=not self._weights_loaded)

    # ---------- 初始化 ----------
    @staticmethod
    def _resolve_weights(spec: str, rerank: bool = False) -> Optional[Path]:
        if spec == "auto":
            base = Path(__file__).resolve().parents[2]
            name = DEFAULT_WEIGHTS_RERANK if rerank else DEFAULT_WEIGHTS
            return base / name
        return Path(spec)

    def _init_from_corpus(self, spec: str, need_train: bool):
        """加载语料：建检索索引（轻量）+ 按需训练语言模型（秒级）。"""
        try:
            from ..eval.corpus import Corpus
            c = Corpus.from_easy_ai() if spec == "auto" else Corpus.from_easy_ai(spec)
            self.build_from_pairs(c.pairs, train=need_train)
        except Exception as e:
            _log.warning("NeuralMatcher 语料加载/训练失败：%s", e)

    # ---------- 训练 ----------
    def build_from_pairs(self, pairs: Sequence[Any], train: bool = True):
        """用问答对构建：AI 侧进 TextCNN（可选训练），用户侧建检索索引。

        Args:
            pairs: 问答对（元组或 QAPair）。
            train: 是否重新训练语言模型。已加载权重时应传 False ——
                   权重管「怎么说话」，语料管「说什么」，后者只需建索引。
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
        self._index.build(qs)
        if train and ans:
            self._cnn.fit(ans, epochs=self._epochs, batch_size=self._batch)
        # 可用的定义：语言模型已就绪（权重或训练）**且**索引非空
        self._ready = bool(ans) and (self._cnn.is_trained or self._weights_loaded)

    # ---------- 匹配 ----------
    def match(self, text: str, rules: List[Dict[str, Any]]) -> Optional[MatchResult]:
        if not self._ready or not self._answers:
            return None
        if self.mode == "rerank":
            return self._match_rerank(text)
        return self._match_generate(text)

    def _match_rerank(self, text: str) -> Optional[MatchResult]:
        """重排序模式：检索出候选原文 → 用 CNN 条件似然挑最贴切的。

        与生成模式的根本区别：**不产出新文本**。候选全部来自真实语料，
        因此天然继承了 P0 建立的「原文保底」质量下限，同时用上了 CNN
        在 teacher-forcing 上的泛化优势（P2 实测 +9.14pp）。
        """
        hits = self._index.retrieve(text, top_n=self.rerank_pool)
        if not hits:
            return None

        idxs = [i for i, _ in hits]
        rels = {i: r for i, r in hits}
        candidates = [self._answers[i] for i in idxs if i < len(self._answers)]
        if not candidates:
            return None

        if self.scorer == "jaccard":
            scores = [self._jaccard(text, c) for c in candidates]
        elif self.scorer == "hybrid":
            cnn_scores = [self._normalize_score(s)
                          for s in self._cnn.score_candidates(text, candidates)]
            jac_scores = [self._jaccard(text, c) for c in candidates]
            a = self.hybrid_alpha
            scores = [a * c + (1 - a) * j for c, j in zip(cnn_scores, jac_scores)]
        else:  # cnn
            scores = [self._normalize_score(s)
                      for s in self._cnn.score_candidates(text, candidates)]

        # 「选得有多确定」：对打分离散度做 softmax，最优候选明显胜出时权重→1，
        # 候选难分时权重→1/池大小。
        # ⚠️ 不能直接用「绝对似然」当置信度：rerank 算的是 P(原文|问题)（条件），
        # 马尔科夫算的是 P(原文)（无条件、记忆型，天然高得多）—— 两者量纲不同，
        # 直接比大小会让 rerank 永远落败（实测 0.09 vs 0.75）。
        choice_conf = self._softmax_top_weight(scores)

        ranked = []
        for idx, cand, sc in zip(idxs, candidates, scores):
            rel = rels.get(idx, 0.0)
            ranked.append((sc, sc, rel, cand, idx))
        if not ranked:
            return None
        ranked.sort(key=lambda x: -x[0])
        _, quality, rel, best, best_idx = ranked[0]

        return MatchResult(
            reply=best,
            confidence=min(rel * choice_conf, 0.75),
            source=self.name,
            metadata={
                "model": "TextCNN",
                "mode": "rerank",
                "pool": len(candidates),
                "cnn_score": round(quality, 4),
                "relevance": round(rel, 4),
                "ranked_count": len(ranked),
            },
        )

    @staticmethod
    def _softmax_top_weight(scores: Sequence[float], temperature: float = 0.05) -> float:
        """最优候选的 softmax 权重 ∈ (0,1]，衡量「选择有多确定」。

        温度取小值：候选间只要有可辨差异，最优项就应获得接近 1 的权重；
        若候选难分伯仲，权重自然回落到 1/池大小。
        """
        import math
        vals = [s for s in scores if s is not None and s != float("-inf")]
        if not vals:
            return 0.0
        top = max(vals)
        exps = [math.exp((s - top) / temperature) for s in vals]
        total = sum(exps)
        return (1.0 / total) if total > 0 else 0.0

    @staticmethod
    def _jaccard(a: str, b: str) -> float:
        """字符 bigram Jaccard —— 朴素词汇匹配打分器。"""
        def grams(t):
            tk = tokenize(t)
            return set((tk[i], tk[i + 1]) for i in range(len(tk) - 1)) or set(tk)
        ga, gb = grams(a or ""), grams(b or "")
        if not ga or not gb:
            return 0.0
        return len(ga & gb) / len(ga | gb)

    def _normalize_score(self, avg_logprob: float) -> float:
        """把每 token 平均对数似然映射到 [0,1]（相对均匀基线增益）。

        与 MarkovChain.confidence / TextCNN.confidence 完全同口径 ——
        0 = 跟瞎猜一样，1 = 确定性预测。
        """
        if avg_logprob is None or avg_logprob == float("-inf"):
            return 0.0
        import math
        V = max(self._cnn.vocab_size, 2)
        log_v = math.log(V)
        return max(0.0, min(1.0, (avg_logprob + log_v) / log_v))

    def _match_generate(self, text: str) -> Optional[MatchResult]:
        hits = self._index.retrieve(text, top_n=1)
        if not hits:
            return None
        idx, relevance = hits[0]
        seed_answer = self._answers[idx] if idx < len(self._answers) else ""
        seed_tokens = tokenize(seed_answer)[:max(2, self._cnn.window)]

        candidates: List[str] = self._cnn.generate_variations(
            seed_tokens, count=self.n_candidates,
            temperature=self.temperature, max_length=self.max_length)
        if seed_answer:
            candidates.append(seed_answer)
        if not candidates:
            return None

        scored = [(self._quality(c), c) for c in candidates]
        scored.sort(key=lambda x: (-x[0], len(x[1])))
        quality, generated = scored[0]

        confidence = min(quality * max(0.0, min(1.0, relevance)), 0.75)

        return MatchResult(
            reply=generated,
            confidence=confidence,
            source=self.name,
            metadata={
                "model": "TextCNN",
                "window": self._cnn.window,
                "temperature": self.temperature,
                "relevance": round(relevance, 4),
                "quality": round(quality, 4),
                "from_weights": self._cnn.is_trained,
            },
        )

    def _quality(self, text: str) -> float:
        """生成序列的质量：相对均匀基线的归一化增益（与 MarkovChain 同口径）。"""
        # 直接委托给 TextCNN.confidence —— 与 MarkovChain.confidence 同口径，
        # 两侧置信度才能公平地放在一起比大小
        return self._cnn.confidence(text)

    # ---------- 接口 ----------
    def retrieve(self, text: str, top_n: int = 3) -> List[Tuple[int, float]]:
        return self._index.retrieve(text, top_n)

    @property
    def model(self) -> TextCNN:
        return self._cnn

    @property
    def is_ready(self) -> bool:
        return self._ready

    def __repr__(self):
        return (f"<NeuralMatcher window={self._cnn.window} "
                f"priority={self.priority} ready={self._ready} "
                f"pairs={len(self._questions)} V={self._cnn.vocab_size}>")
