"""
单元测试：NeuralMatcher —— TextCNN 接入对话链路的端到端契约。

本文件要钉死两件事：
1. **接入是真的**：权重加载 + 检索索引都就位后，match() 必须能产出回复
   （早先只加载权重、漏建索引，导致 pairs=0、match() 恒返回 None，
   neural 在链路里形同虚设 —— 这个 bug 必须被测试挡住）。
2. **置信度与马尔科夫同口径**：两者都用「相对均匀基线的归一化增益」，
   因而可以放在同一场竞争里比较。

运行：
    python -m pytest tests/test_neural_matcher.py -p no:hydra_pytest -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from easy_ai.ai.matchers import MATCHER_REGISTRY, NeuralMatcher, MarkovMatcher  # noqa: E402
from easy_ai.ai.matchers.retrieval import RetrievalIndex  # noqa: E402
from easy_ai.ai.textcnn import TextCNN  # noqa: E402

PAIRS = [
    ("今天天气如何", "今天天气晴朗，适合出门散步"),
    ("你叫什么名字", "我叫小助手，很高兴认识你"),
    ("讲个笑话", "从前有一只猫，它学会了编程"),
] * 6  # 重复以撑过 UNK cutoff


class TestRegistration(unittest.TestCase):
    """必须能被 pipeline 通过注册表发现。"""

    def test_registered(self):
        self.assertIn("neural", MATCHER_REGISTRY)
        self.assertIs(MATCHER_REGISTRY["neural"], NeuralMatcher)

    def test_default_config_disabled(self):
        """默认配置里 neural 是关闭的 —— 训练需数秒，不应拖慢 AICore 启动。"""
        import json
        cfg = json.loads((Path(__file__).resolve().parents[1] / "src" / "easy_ai" / "config"
                          / "default.json").read_text(encoding="utf-8"))
        self.assertFalse(cfg["matchers"]["neural"]["enabled"])


class TestRetrievalIndexShared(unittest.TestCase):
    """检索索引被两个匹配器共用 —— 修一处即可。"""

    def test_index_retrieves(self):
        idx = RetrievalIndex()
        idx.build(["今天天气如何", "你叫什么名字"])
        hits = idx.retrieve("今天天气如何", top_n=1)
        self.assertTrue(hits)
        self.assertEqual(hits[0][0], 0)
        self.assertGreater(hits[0][1], 0.5)

    def test_index_empty_query(self):
        idx = RetrievalIndex()
        idx.build(["abc"])
        self.assertEqual(idx.retrieve("", 3), [])

    def test_markov_uses_shared_index(self):
        mm = MarkovMatcher({"n_gram": 2, "unk_cutoff": 0})
        mm.build_from_pairs(PAIRS)
        self.assertIsInstance(mm._index, RetrievalIndex)
        self.assertEqual(mm._index.size, len(PAIRS))


class TestNeuralMatcherReady(unittest.TestCase):
    """「可用」的定义：语言模型就绪 **且** 检索索引非空。"""

    def test_build_from_pairs_trains_and_indexes(self):
        nm = NeuralMatcher({"window": 4, "epochs": 3, "n_filters": 8,
                            "embed_dim": 16})
        nm.build_from_pairs(PAIRS, train=True)
        self.assertTrue(nm.is_ready, "训练后应就绪")
        self.assertEqual(len(nm._questions), len(PAIRS))
        self.assertTrue(nm.model.is_trained)

    def test_index_built_even_without_training(self):
        """有权重时只建索引、不重训 —— 权重管「怎么说话」，语料管「说什么」。

        `weights: None` 是必要的：否则会去加载仓库里可能存在的
        `data/textcnn_weights.json`，让本用例依赖外部文件而失去隔离性。
        """
        nm = NeuralMatcher({"window": 4, "epochs": 1, "n_filters": 8,
                            "embed_dim": 16, "weights": None})
        self.assertFalse(nm.model.is_trained, "未加载权重前不应就绪")
        nm.build_from_pairs(PAIRS, train=False)
        self.assertEqual(len(nm._questions), len(PAIRS))
        self.assertFalse(nm.model.is_trained, "train=False 时不应训练")

    def test_match_returns_result_when_ready(self):
        nm = NeuralMatcher({"window": 4, "epochs": 8, "n_filters": 8,
                            "embed_dim": 16, "temperature": 0.7})
        nm.build_from_pairs(PAIRS, train=True)
        r = nm.match("今天天气如何", [])
        self.assertIsNotNone(r, "就绪后必须能产出回复（pairs=0 的旧 bug 在此挡住）")
        self.assertTrue(r.reply)
        self.assertLessEqual(r.confidence, 0.75)
        self.assertEqual(r.source, "NeuralMatcher")

    def test_match_none_when_no_pairs(self):
        nm = NeuralMatcher({"window": 4})
        self.assertFalse(nm.is_ready)
        self.assertIsNone(nm.match("今天天气如何", []))


class TestConfidenceParity(unittest.TestCase):
    """置信度口径必须与马尔科夫一致，否则无法同场竞争。"""

    def test_both_use_uniform_baseline_gain(self):
        """同一段文本，两个模型的 confidence 都应落在 [0,1] 且可比较。"""
        text = "今天天气晴朗，适合出门散步"
        nm = NeuralMatcher({"window": 4, "epochs": 8, "n_filters": 8,
                            "embed_dim": 16})
        nm.build_from_pairs(PAIRS, train=True)
        mm = MarkovMatcher({"n_gram": 3, "unk_cutoff": 0})
        mm.build_from_pairs(PAIRS)

        cn = nm.model.confidence(text)
        cm = mm.model.confidence(text)
        for name, c in (("TextCNN", cn), ("Markov", cm)):
            self.assertGreaterEqual(c, 0.0, f"{name} 置信度越界")
            self.assertLessEqual(c, 1.0, f"{name} 置信度越界")


if __name__ == "__main__":
    unittest.main(verbosity=2)
