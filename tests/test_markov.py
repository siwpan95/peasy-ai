"""
单元测试：马尔科夫链语言模型（P0 改造后的回归门禁）

本文件的核心是**合成可判定用例**（口径取自 weiqi_lab `tools/tests_markov.mjs`）：
用人工构造的、正确答案**事先已知**的最小语料，把「模型是否真的学到了转移」
变成一个非此即彼的断言，而不是"看起来能跑"。

钉死的三个历史缺陷：
- D4 伪置信度（Jaccard 冒充置信度）→ `test_confidence_discriminates_seen_vs_unseen`
- D9 语义错位（用输入续写充当回复）→ `test_matcher_reply_is_not_user_continuation`
- D6 无平滑（未见组合概率归零）→ `test_smoothing_gives_nonzero_probability`

运行：
    python -m pytest tests/test_markov.py -v
    python -m unittest tests.test_markov
"""

import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from easy_ai.ai.eval import tokenize, BOS, EOS, UNK
from easy_ai.ai.matchers.markov_chain import MarkovChain, MarkovMatcher


# ================================================================
# 合成语料：两条互不相交的确定链
#   甲乙 → 丙      （重复 20 次）
#   戊己 → 庚      （重复 20 次）
# 任何正确实现的 top-1 都必须分别是「丙」「庚」。
# ================================================================
DETERMINISTIC_CORPUS = ["甲乙丙"] * 20 + ["戊己庚"] * 20


class TestDeterministicTransitions(unittest.TestCase):
    """合成可判定用例：模型必须学到确定性转移。"""

    def test_top1_hits_known_transition(self):
        """P(丙 | 甲乙) 与 P(庚 | 戊己) 必须各自排第一。"""
        for smoothing in ("none", "add_k", "kneser_ney"):
            with self.subTest(smoothing=smoothing):
                m = MarkovChain(n=3, smoothing=smoothing, unk_cutoff=0)
                m.train(DETERMINISTIC_CORPUS)

                top = m.top_k(["甲", "乙"], 1)
                self.assertTrue(top, f"{smoothing}: top_k 返回空")
                self.assertEqual(top[0][0], "丙",
                                 f"{smoothing}: P(丙|甲乙) 应排第一，实得 {top}")

                top2 = m.top_k(["戊", "己"], 1)
                self.assertEqual(top2[0][0], "庚",
                                 f"{smoothing}: P(庚|戊己) 应排第一，实得 {top2}")

    def test_cross_chain_not_confused(self):
        """两条链互不混淆：P(庚|甲乙) 必须明显小于 P(丙|甲乙)。"""
        m = MarkovChain(n=3, smoothing="kneser_ney", unk_cutoff=0)
        m.train(DETERMINISTIC_CORPUS)
        p_right = m.prob(["甲", "乙"], "丙")
        p_wrong = m.prob(["甲", "乙"], "庚")
        self.assertGreater(p_right, p_wrong * 5,
                           f"正确转移应显著占优：P(丙)={p_right:.4f} vs P(庚)={p_wrong:.4f}")

    def test_top1_far_above_uniform(self):
        """top-1 命中率必须显著高于均匀基线（否则模型等于没学）。"""
        m = MarkovChain(n=3, smoothing="kneser_ney", unk_cutoff=0)
        m.train(DETERMINISTIC_CORPUS)
        hit = total = 0
        for text in ["甲乙丙", "戊己庚"]:
            toks = [BOS] + tokenize(text) + [EOS]
            for i in range(1, len(toks)):
                preds = m.top_k(toks[:i], 1)
                if preds:
                    total += 1
                    hit += 1 if preds[0][0] == toks[i] else 0
        acc = hit / total if total else 0.0
        uniform = 1.0 / max(m.vocab_size, 1)
        self.assertGreater(acc, uniform * 3,
                           f"top-1 {acc:.3f} 应显著高于均匀基线 {uniform:.3f}")


class TestSmoothing(unittest.TestCase):
    """D6：平滑必须消除零概率。"""

    def test_smoothing_gives_nonzero_probability(self):
        """词表内任意 token，在未见组合下概率也必须 > 0。"""
        for smoothing in ("add_k", "kneser_ney"):
            with self.subTest(smoothing=smoothing):
                m = MarkovChain(n=3, smoothing=smoothing, unk_cutoff=0, k=0.1)
                m.train(DETERMINISTIC_CORPUS)
                # 「辛」从未在语料中出现过 —— 无平滑时会是 0
                p = m.prob(["甲", "乙"], "辛")
                self.assertGreater(p, 0.0,
                                   f"{smoothing}: 未见 token 概率被平滑成了 0")

    def test_kneser_ney_uses_continuation_counts(self):
        """KN 的特征：低阶分布按「出现在多少种上下文」而非「出现多少次」。

        「丙」只出现在「甲乙」这一种上下文 → 延续计数低；
        「庚」只出现在「戊己」 → 同样低。二者 unigram 应接近相等，
        若退回原始频次则会因计数相同而看不出差异（此处只做结构校验）。
        """
        m = MarkovChain(n=3, smoothing="kneser_ney", unk_cutoff=0)
        m.train(DETERMINISTIC_CORPUS)
        self.assertTrue(m._continuation, "KN 应构建延续计数")
        self.assertIn("丙", m._continuation.get(3, {}))
        self.assertIn("庚", m._continuation.get(3, {}))

    def test_probabilities_sum_to_one(self):
        """同一上下文下，全部候选 token 的概率之和应≈1（概率分布的定义）。"""
        m = MarkovChain(n=3, smoothing="kneser_ney", unk_cutoff=0)
        m.train(DETERMINISTIC_CORPUS)
        cands = set()
        for level in range(3, 0, -1):
            d = m._counts.get(level, {}).get(m._tail(["甲", "乙"], level - 1))
            if d:
                cands.update(d.keys())
        total = sum(m.prob(["甲", "乙"], w) for w in cands)
        # 允许平滑留出的未见事件质量，故只要求落在合理区间
        self.assertGreater(total, 0.5, f"概率质量过小：{total:.3f}")
        self.assertLessEqual(total, 1.2, f"概率质量超过 1：{total:.3f}")


class TestUnknownFolding(unittest.TestCase):
    """UNK 折叠：小语料下 perplexity 的主要杀手。"""

    def test_low_frequency_tokens_folded(self):
        """出现次数 <= cutoff 的词应被折叠进 <unk>。"""
        corpus = ["甲乙丙"] * 10 + ["独一味"]  # 「独」「一」「味」各只出现 1 次
        m = MarkovChain(n=2, unk_cutoff=1)
        m.train(corpus)
        self.assertIn(UNK, m.vocab)
        self.assertNotIn("独", m._kept, "低频词不应留在保留词表")

    def test_unseen_token_maps_to_unk(self):
        """评估时未见 token 必须映射为 <unk>，而非概率归零。"""
        m = MarkovChain(n=2, unk_cutoff=1)
        m.train(["甲乙丙"] * 10)
        self.assertEqual(m._norm("這是一個完全沒見過的字"), UNK)
        self.assertGreater(math.exp(m.log_prob(["甲"], "這是一個完全沒見過的字")), 0.0)


class TestConfidence(unittest.TestCase):
    """D4：置信度必须是「模型质量」，不是字符重叠。"""

    def test_confidence_discriminates_seen_vs_unseen(self):
        """见过的高频序列，置信度必须显著高于乱码。

        旧版用 Jaccard(输入, 生成文本) 计算置信度 —— 与生成质量无关，
        对这两类输入会给出相近甚至相反的值。本用例即用于钉死该缺陷。
        """
        m = MarkovChain(n=3, smoothing="kneser_ney", unk_cutoff=0)
        m.train(DETERMINISTIC_CORPUS)

        c_seen = m.confidence("甲乙丙")
        c_unseen = m.confidence("這貨沒在語料裡出現過吧隨便打的")
        self.assertGreater(c_seen, c_unseen + 0.2,
                           f"置信度失去区分度：见过 {c_seen:.3f} vs 未见 {c_unseen:.3f}")

    def test_confidence_bounded(self):
        for text in ["", "甲乙丙", "亂七八糟", "甲乙丙丁戊己庚"]:
            c = MarkovChain(n=3, unk_cutoff=0).confidence(text)
            # 未训练时也应安全返回 0
            self.assertGreaterEqual(c, 0.0)
            self.assertLessEqual(c, 1.0)

    def test_confidence_zero_when_untrained(self):
        m = MarkovChain(n=3)
        self.assertEqual(m.confidence("甲乙丙"), 0.0)


class TestPersistence(unittest.TestCase):
    """save / load：为 P2 蒸馏与随仓分发铺路。"""

    def test_roundtrip_preserves_probabilities(self):
        m = MarkovChain(n=3, smoothing="kneser_ney", unk_cutoff=1)
        m.train(DETERMINISTIC_CORPUS + ["壬癸子"] * 5)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "m.json")
            m.save(p)
            m2 = MarkovChain.load(p)
        self.assertEqual(m.n, m2.n)
        self.assertEqual(m.smoothing, m2.smoothing)
        for ctx, tok in ((["甲", "乙"], "丙"), (["戊", "己"], "庚")):
            self.assertAlmostEqual(m.prob(ctx, tok), m2.prob(ctx, tok), places=9,
                                   msg=f"存取后概率漂移：{ctx}→{tok}")


class TestMatcherSemantics(unittest.TestCase):
    """D9：回复必须来自 AI 侧分布，而不是用户输入的续写。"""

    PAIRS = [
        ("今天天气如何", "今天天气晴朗，适合出门散步"),
        ("你叫什么名字", "我叫小助手，很高兴认识你"),
        ("讲个笑话", "从前有一只猫，它学会了编程"),
    ]

    def _make(self, **kw):
        mm = MarkovMatcher({"n_gram": 3, "temperature": 0.7, **kw})
        mm.build_from_pairs(self.PAIRS)
        return mm

    def test_matcher_reply_is_not_user_continuation(self):
        """回复不得以「完整用户输入」开头 —— 那是续写，不是回复。"""
        mm = self._make()
        q = "今天天气如何"
        r = mm.match(q, [])
        self.assertIsNotNone(r, "应能产出回复")
        self.assertFalse(r.reply.startswith(q),
                         f"回复被生成为用户输入的续写：{r.reply!r}")

    def test_ai_chain_trained_on_answers_only(self):
        """AI 链的词表只应含答案里的字，不该含问题里的独有字。

        注：此处 unk_cutoff=0 —— 只隔离「用户/AI 语料是否分离」这一件事。
        若用默认 cutoff=1，这条 6 字的答案会被整体折叠成 <unk>（语料太小），
        那是 UNK 折叠的既定行为，不是本用例要测的东西。
        """
        pairs = [("量子隧穿效应", "这是一个物理现象")]
        mm = MarkovMatcher({"n_gram": 2, "unk_cutoff": 0})
        mm.build_from_pairs(pairs)
        vocab = mm.model.vocab
        # 「隧」「穿」只出现在问题里，不该泄漏进 AI 侧模型
        self.assertNotIn("隧", vocab, "用户语料泄漏进了 AI 侧模型")
        self.assertNotIn("穿", vocab, "用户语料泄漏进了 AI 侧模型")
        self.assertIn("物", vocab, "AI 语料未进入模型")

    def test_retrieval_finds_relevant_pair(self):
        """倒排索引应能把输入检索到对应问答对。"""
        mm = self._make()
        hits = mm.retrieve("今天天气如何", top_n=1)
        self.assertTrue(hits, "检索无结果")
        idx, score = hits[0]
        self.assertEqual(mm._questions[idx], "今天天气如何")
        self.assertGreater(score, 0.5)

    def test_match_confidence_below_rules(self):
        """马尔科夫是创意兜底，置信度上限 0.75，不应压过规则精确匹配(0.95)。"""
        mm = self._make()
        r = mm.match("今天天气如何", [])
        self.assertIsNotNone(r)
        self.assertLessEqual(r.confidence, 0.75)

    def test_unknown_input_yields_none(self):
        """完全无关的输入：检索不到就不该硬凑。"""
        mm = self._make()
        self.assertIsNone(mm.match("zzz qqq 完全不相关的输入", []))


class TestBackwardCompatibility(unittest.TestCase):
    """保持 main.py markov-demo 等既有调用可用。"""

    def test_legacy_train_and_sample(self):
        m = MarkovChain(n=3)
        m.train(["甲乙丙丁戊己"] * 8)
        self.assertTrue(m.is_trained)
        self.assertIsInstance(m.sample(start="甲乙", max_length=12), str)

    def test_legacy_generate_variations(self):
        m = MarkovChain(n=3)
        m.train(["春风又绿江南岸"] * 8)
        vs = m.generate_variations("春风", count=3)
        self.assertLessEqual(len(vs), 3)
        self.assertTrue(all(isinstance(v, str) for v in vs))

    def test_legacy_properties(self):
        m = MarkovChain(n=2)
        m.train(["甲乙丙"] * 5)
        self.assertIsInstance(m.vocab_size, int)
        self.assertIsInstance(m.total_states, int)
        self.assertGreater(m.vocab_size, 0)

    def test_legacy_transition_probability(self):
        m = MarkovChain(n=2, unk_cutoff=0)
        m.train(["甲乙"] * 10)
        p = m.get_transition_probability(("甲",), "乙")
        self.assertGreater(p, 0.5)

    def test_build_from_rules_still_works(self):
        rules = [{"pattern": "你好|嗨", "responses": ["你好呀！", "嗨！"]}]
        mm = MarkovMatcher({"n_gram": 2})
        mm.build_from_rules(rules)
        self.assertTrue(mm.model.is_trained)
        r = mm.match("你好", rules)
        self.assertIsNotNone(r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
