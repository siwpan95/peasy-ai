"""
单元测试：评估地基（ai.eval）

评估框架本身必须是可信的 —— 如果尺子会撒谎，基于它做的所有优化都是空中楼阁。
本文件校验三件事：
1. 留出集划分**确定性**且**无泄漏**（训练集里不能出现留出集的文档）；
2. 基线数学正确（均匀基线的 perplexity = 词表大小，top-1 = 1/V）；
3. 指标对「更好的模型」敏感 —— 用合成语料验证 perplexity 能区分优劣。

运行：
    python -m pytest tests/test_eval.py -p no:hydra_pytest -v
"""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ai.eval import (
    Corpus, QAPair, tokenize, detokenize, BOS, EOS, UNK,
    evaluate, format_report, perplexity, top_k_accuracy,
    uniform_baseline, oov_rate, coverage, relative_gain,
)
from ai.matchers.markov_chain import MarkovChain


class TestTokenizer(unittest.TestCase):
    """分词器是全项目唯一真相来源：train/test 必须同源。"""

    def test_chinese_split_by_char(self):
        self.assertEqual(tokenize("今天天气"), ["今", "天", "天", "气"])

    def test_english_kept_as_word(self):
        self.assertIn("hello", tokenize("say hello world"))

    def test_empty(self):
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize(None), [])

    def test_detokenize_drops_boundaries(self):
        self.assertNotIn(BOS, detokenize([BOS, "今", "天", EOS]))
        self.assertNotIn(UNK, detokenize(["今", UNK, "天"]))

    def test_round_trip_readable(self):
        """中文切分后还原应得到可读文本（不插入多余空格）。"""
        self.assertEqual(detokenize(tokenize("今天天气晴朗")), "今天天气晴朗")


class TestCorpusSplit(unittest.TestCase):
    """留出集划分：确定性 + 无泄漏 + 确定性可复现。"""

    def _corpus(self):
        return Corpus("t",
                      texts=["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"],
                      pairs=[QAPair(f"q{i}", f"a{i}", "test") for i in range(10)])

    def test_split_sizes(self):
        tr, ho = self._corpus().split(0.8)
        self.assertEqual(len(tr.texts), 8)
        self.assertEqual(len(ho.texts), 2)
        self.assertEqual(len(tr.pairs), 8)
        self.assertEqual(len(ho.pairs), 2)

    def test_split_is_deterministic(self):
        a1, b1 = self._corpus().split(0.8)
        a2, b2 = self._corpus().split(0.8)
        self.assertEqual(a1.texts, a2.texts)
        self.assertEqual(b1.texts, b2.texts)

    def test_no_leakage(self):
        """训练集与留出集不得有交集 —— 否则 perplexity 会虚低。"""
        tr, ho = self._corpus().split(0.8)
        self.assertFalse(set(tr.texts) & set(ho.texts), "纯文本存在泄漏")
        self.assertFalse({p.question for p in tr.pairs} &
                         {p.question for p in ho.pairs}, "问答对存在泄漏")

    def test_invalid_ratio(self):
        with self.assertRaises(ValueError):
            self._corpus().split(1.5)
        with self.assertRaises(ValueError):
            self._corpus().split(0.0)

    def test_user_ai_views_separated(self):
        """user_texts / ai_texts 必须分别来自问与答，不能混。"""
        c = Corpus("t", pairs=[QAPair("问一", "答一"), QAPair("问二", "答二")])
        self.assertEqual(c.user_texts, ["问一", "问二"])
        self.assertEqual(c.ai_texts, ["答一", "答二"])


class TestBaselineMath(unittest.TestCase):
    """基线数学：错了就会让所有「相对增益」失去意义。"""

    def test_uniform_baseline(self):
        b = uniform_baseline(100)
        self.assertEqual(b["perplexity"], 100.0)
        self.assertAlmostEqual(b["top1"], 0.01)
        self.assertAlmostEqual(b["top3"], 0.03)

    def test_uniform_baseline_degenerate(self):
        b = uniform_baseline(0)
        self.assertEqual(b["perplexity"], float("inf"))

    def test_relative_gain(self):
        self.assertAlmostEqual(relative_gain(0.5, 0.1), 5.0)
        self.assertEqual(relative_gain(1.0, 0.0), 0.0)   # 防零
        self.assertEqual(relative_gain(0.0, 0.5), 0.0)


class TestMetricsSensitivity(unittest.TestCase):
    """指标必须能区分模型好坏 —— 否则它就是个摆设。"""

    def test_perplexity_beats_uniform_on_learned_corpus(self):
        """在模型学过的确定性语料上，perplexity 必须远低于均匀基线。"""
        m = MarkovChain(n=3, smoothing="kneser_ney", unk_cutoff=0)
        m.train(["甲乙丙丁"] * 20)
        pp = perplexity(m, ["甲乙丙丁"])
        self.assertLess(pp, m.vocab_size,
                        f"perplexity {pp:.2f} 未优于均匀基线 {m.vocab_size}")

    def test_perplexity_worse_on_unseen(self):
        """未见过的文本，perplexity 必然高于训练文本。"""
        m = MarkovChain(n=3, smoothing="kneser_ney", unk_cutoff=0)
        m.train(["甲乙丙丁"] * 20)
        pp_seen = perplexity(m, ["甲乙丙丁"])
        pp_unseen = perplexity(m, ["這貨完全沒學過"])
        self.assertGreater(pp_unseen, pp_seen,
                           f"未见文本 perplexity({pp_unseen:.1f}) 应高于已见({pp_seen:.1f})")

    def test_top_k_accuracy_better_than_uniform(self):
        m = MarkovChain(n=3, smoothing="kneser_ney", unk_cutoff=0)
        m.train(["甲乙丙丁"] * 20)
        acc = top_k_accuracy(m, ["甲乙丙丁"], k=1)
        self.assertGreater(acc, 1.0 / m.vocab_size)

    def test_oov_reported(self):
        m = MarkovChain(n=2, unk_cutoff=0)
        m.train(["甲乙丙"] * 5)
        r = oov_rate(m, ["這是沒見過的"])
        self.assertIsNotNone(r)
        self.assertGreater(r, 0.0)

    def test_metrics_handle_empty(self):
        m = MarkovChain(n=2, unk_cutoff=0)
        m.train(["甲乙"] * 3)
        self.assertEqual(perplexity(m, []), float("inf"))
        self.assertIn("error", evaluate(m, []))

    def test_evaluate_returns_all_fields(self):
        m = MarkovChain(n=2, unk_cutoff=0)
        m.train(["甲乙丙丁"] * 10)
        r = evaluate(m, ["甲乙丙"])
        for key in ("perplexity", "top1", "top3", "uniform_top1",
                    "top1_gain", "coverage", "oov_rate", "vocab_size"):
            self.assertIn(key, r, f"评估结果缺少字段 {key}")

    def test_format_report_runs(self):
        m = MarkovChain(n=2, unk_cutoff=0)
        m.train(["甲乙丙丁"] * 10)
        out = format_report(evaluate(m, ["甲乙丙"]), "冒烟")
        self.assertIn("perplexity", out)


class TestRealCorpus(unittest.TestCase):
    """用项目真实语料做冒烟（不写死数字，只校验结构健全）。"""

    def test_loads_real_corpus(self):
        c = Corpus.from_easy_ai()
        self.assertGreater(len(c.pairs), 0, "真实语料应至少有一些问答对")
        st = c.stats()
        self.assertGreater(st["tokens"], 0)
        self.assertIn("training_log", st["sources"])

    def test_real_corpus_eval_smoke(self):
        c = Corpus.from_easy_ai()
        tr, ho = c.split(0.8)
        m = MarkovChain(n=3, smoothing="kneser_ney", unk_cutoff=1)
        m.train(tr.ai_texts or tr.all_texts)
        r = evaluate(m, ho.all_texts)
        self.assertGreater(r["tokens"], 0)
        # 真实小语料上至少应优于瞎猜
        self.assertGreater(r["top1"], r["uniform_top1"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
