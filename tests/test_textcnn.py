"""
单元测试：TextCNN（P2）

最关键的一项是**梯度检查**：用有限差分验证反向传播。理由很简单 ——
一个「看起来 loss 在降」的网络，可能梯度是错的却照样下降（尤其在小语料上），
只有数值校验能证明它真的是在按正确的方向学习。
（weiqi_lab 的 `ml/gradcheck.py` 是同一思路。）

其余用例沿用 P0 建立的纪律：合成可判定用例 + 与马尔科夫链的公平对照前提。

运行：
    python -m pytest tests/test_textcnn.py -p no:hydra_pytest -v
"""

import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np

from ai.eval import tokenize, BOS, EOS, UNK, evaluate, perplexity
from ai.matchers.markov_chain import MarkovChain
from ai.textcnn import TextCNN, PAD_ID


# 两条互不相交的确定链（与 test_markov.py 同构，便于跨模型比较）
DETERMINISTIC = ["甲乙丙丁"] * 40 + ["戊己庚辛"] * 40


def _small_model(**kw):
    cfg = dict(window=5, embed_dim=8, n_filters=4, kernel_sizes=(2, 3),
               dropout=0.0, lr=0.1, seed=1, unk_cutoff=0)
    cfg.update(kw)
    return TextCNN(**cfg)


class TestGradientCheck(unittest.TestCase):
    """有限差分 vs 解析梯度 —— 证明反向传播真的正确。"""

    def test_all_parameters_gradient_correct(self):
        m = _small_model()
        m.build_vocab(DETERMINISTIC)
        m._init_params()
        X, y = m.build_samples(DETERMINISTIC)
        xb, yb = X[:8], y[:8]

        def loss_fn():
            logits, _ = m._forward(xb, training=False)
            p = m._softmax(logits)
            return -np.log(np.maximum(p[np.arange(len(yb)), yb], 1e-12)).sum()

        grads = {k: np.zeros_like(v) for k, v in m._params.items()}
        logits, cache = m._forward(xb, training=False)
        p = m._softmax(logits)
        d = p.copy()
        d[np.arange(len(yb)), yb] -= 1.0
        m._backward(d, cache, grads)

        eps = 1e-4
        rng = np.random.RandomState(0)
        for name, P in m._params.items():
            flat = P.size
            worst = 0.0
            for _ in range(6):
                idx = np.unravel_index(rng.randint(0, flat), P.shape)
                orig = P[idx]
                P[idx] = orig + eps
                lp = loss_fn()
                P[idx] = orig - eps
                lm = loss_fn()
                P[idx] = orig
                num = (lp - lm) / (2 * eps)
                ana = grads[name][idx]
                denom = max(abs(num), abs(ana), 1e-8)
                worst = max(worst, abs(num - ana) / denom)
            self.assertLess(worst, 1e-4,
                            f"参数 {name} 梯度不匹配，最大相对误差 {worst:.3e}")


class TestLearning(unittest.TestCase):
    """必须真的能从数据里学到东西。"""

    def test_loss_decreases(self):
        m = _small_model()
        m.build_vocab(DETERMINISTIC)
        hist = m.fit(DETERMINISTIC, epochs=12, batch_size=32)["history"]
        self.assertGreater(len(hist), 1)
        self.assertLess(hist[-1]["loss"], hist[0]["loss"],
                        f"loss 未下降：{hist[0]['loss']:.4f} → {hist[-1]['loss']:.4f}")

    def test_can_memorize_deterministic_chain(self):
        """合成可判定：训练后在同分布文本上的 top-1 必须显著高于均匀基线。"""
        m = _small_model(window=4, embed_dim=16, n_filters=8, lr=0.2)
        m.build_vocab(DETERMINISTIC)
        m.fit(DETERMINISTIC, epochs=60, batch_size=32)
        p_correct = m.prob([BOS, "甲", "乙"], "丙")
        p_wrong = m.prob([BOS, "甲", "乙"], "辛")
        self.assertGreater(p_correct, p_wrong,
                           f"未学到转移：P(丙)={p_correct:.4f} vs P(辛)={p_wrong:.4f}")

    def test_beats_uniform_on_learned_corpus(self):
        m = _small_model(window=4, embed_dim=16, n_filters=8, lr=0.2)
        m.fit(DETERMINISTIC, epochs=40, batch_size=32)
        pp = perplexity(m, ["甲乙丙丁"])
        self.assertLess(pp, m.vocab_size,
                        f"perplexity {pp:.2f} 未优于均匀基线 {m.vocab_size}")


class TestEvalProtocolParity(unittest.TestCase):
    """与马尔科夫链共用评估协议 —— 这是公平对照的前提。"""

    def test_same_vocab_and_unk_mapping_as_markov(self):
        """同 cutoff 下，两者词表与 UNK 归一必须一致，否则 perplexity 不可比。"""
        corpus = ["甲乙丙丁"] * 10 + ["独一味"]  # 「独」「一」「味」是低频词
        mc = MarkovChain(n=3, unk_cutoff=1)
        mc.train(corpus)
        cnn = TextCNN(window=4, unk_cutoff=1)
        cnn.build_vocab(corpus)
        # 词表集合一致（CNN 多一个 PAD，比较时排除）
        self.assertEqual(mc.vocab - {UNK}, cnn.vocab - {UNK})
        self.assertEqual(mc._norm("独"), cnn._norm("独"))

    def test_exposes_evaluation_protocol(self):
        m = _small_model()
        m.fit(DETERMINISTIC, epochs=3)
        self.assertIsInstance(m.log_prob(["甲", "乙"], "丙"), float)
        self.assertTrue(m.top_k(["甲", "乙"], 3))
        self.assertGreater(m.vocab_size, 0)
        self.assertIsInstance(m.vocab, set)

    def test_evaluate_works_on_cnn(self):
        """ai.eval.evaluate 必须能直接吃 TextCNN（协议兼容）。"""
        m = _small_model(window=4, embed_dim=16, n_filters=8)
        m.fit(DETERMINISTIC, epochs=20, batch_size=32)
        r = evaluate(m, ["甲乙丙丁"])
        for key in ("perplexity", "top1", "top3", "uniform_top1", "oov_rate"):
            self.assertIn(key, r, f"评估结果缺少字段 {key}")


class TestPersistence(unittest.TestCase):
    """权重导出 —— 为「零依赖运行期」铺路。"""

    def test_roundtrip_preserves_probabilities(self):
        m = _small_model(window=4, embed_dim=8, n_filters=4)
        m.fit(DETERMINISTIC, epochs=5)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "cnn.json")
            m.save(p)
            m2 = TextCNN.load(p)
        self.assertEqual(m.vocab_size, m2.vocab_size)
        for ctx, tok in (([BOS, "甲", "乙"], "丙"), ([BOS, "戊", "己"], "庚")):
            self.assertAlmostEqual(m.prob(ctx, tok), m2.prob(ctx, tok), places=9,
                                   msg=f"存取后概率漂移：{ctx}→{tok}")


class TestEdgeCases(unittest.TestCase):
    """边界：短文本、空输入、未训练。"""

    def test_short_context_padded(self):
        m = _small_model(window=8)
        m.fit(DETERMINISTIC, epochs=3)
        # 上下文短于 window：应左填充而不是崩
        self.assertIsInstance(m.prob(["甲"], "乙"), float)

    def test_empty_context(self):
        m = _small_model()
        m.fit(DETERMINISTIC, epochs=3)
        self.assertIsInstance(m.prob([], "甲"), float)

    def test_untrained_returns_floor(self):
        m = _small_model()
        self.assertEqual(m.top_k(["甲"], 1), [])
        self.assertLessEqual(m.log_prob(["甲"], "乙"), 0.0)

    def test_unknown_token_maps_to_unk(self):
        m = _small_model(unk_cutoff=1)
        m.build_vocab(["甲乙丙"] * 10)
        self.assertEqual(m._norm("這個字沒見過"), UNK)


if __name__ == "__main__":
    unittest.main(verbosity=2)
