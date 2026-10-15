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

# 权重默认位置（相对项目根）
DEFAULT_WEIGHTS = "data/textcnn_weights.json"


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
            path = self._resolve_weights(weights)
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
    def _resolve_weights(spec: str) -> Optional[Path]:
        if spec == "auto":
            return Path(__file__).resolve().parents[2] / DEFAULT_WEIGHTS
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
