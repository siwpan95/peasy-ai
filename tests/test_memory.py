"""
单元测试：MemoryStore

测试覆盖：
- 学习/遗忘
- 查询/模糊搜索
- 会话管理
- 序列化/持久化
- 线程安全
"""

import unittest
import tempfile
import os
import json
from pathlib import Path

# 添加项目根目录到路径
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from easy_ai.ai.memory import MemoryStore


class TestMemoryStore(unittest.TestCase):
    """MemoryStore 单元测试。"""

    def setUp(self):
        """每个测试前的设置。"""
        self.memory = MemoryStore()

    def test_learn_new_question(self):
        """测试学习新问题。"""
        result = self.memory.learn("你好", "你好呀！")
        self.assertTrue(result)
        self.assertEqual(len(self.memory), 1)

    def test_learn_duplicate_answer(self):
        """测试学习重复答案（应该返回 False）。"""
        self.memory.learn("你好", "你好呀！")
        result = self.memory.learn("你好", "你好呀！")
        self.assertFalse(result)
        self.assertEqual(self.memory.total_answers, 1)

    def test_learn_multiple_answers(self):
        """测试为一个问题学习多个答案。"""
        self.memory.learn("你好", "你好呀！")
        self.memory.learn("你好", "嗨！")
        self.assertEqual(self.memory.total_answers, 2)

    def test_forget_question(self):
        """测试忘记问题。"""
        self.memory.learn("你好", "你好呀！")
        result = self.memory.forget("你好")
        self.assertTrue(result)
        self.assertEqual(len(self.memory), 0)

    def test_forget_nonexistent(self):
        """测试忘记不存在的问题。"""
        result = self.memory.forget("不存在")
        self.assertFalse(result)

    def test_get_exact_match(self):
        """测试精确匹配查询。"""
        self.memory.learn("你好", "你好呀！")
        reply = self.memory.get("你好")
        self.assertEqual(reply, "你好呀！")

    def test_get_nonexistent(self):
        """测试查询不存在的问题。"""
        reply = self.memory.get("不存在")
        self.assertIsNone(reply)

    def test_fuzzy_search(self):
        """测试模糊搜索。"""
        self.memory.learn("你好呀", "嗨！")
        found, question = self.memory.fuzzy_search("你好")
        self.assertTrue(found)
        self.assertEqual(question, "你好呀")

    def test_search_by_keyword(self):
        """测试关键词搜索。"""
        self.memory.learn("你好吗", "我很好")
        self.memory.learn("你好呀", "嗨！")
        results = self.memory.search("你好")
        self.assertEqual(len(results), 2)

    def test_clear(self):
        """测试清空记忆。"""
        self.memory.learn("Q1", "A1")
        self.memory.learn("Q2", "A2")
        self.memory.clear()
        self.assertEqual(len(self.memory), 0)
        self.assertEqual(self.memory.total_answers, 0)

    def test_session_save_load(self):
        """测试会话保存和加载。"""
        history = [("user", "你好"), ("ai", "你好呀！")]
        self.memory.save_session("session1", history)
        loaded = self.memory.load_session("session1")
        self.assertEqual(loaded, history)

    def test_session_delete(self):
        """测试删除会话。"""
        self.memory.save_session("session1", [("user", "hi")])
        result = self.memory.delete_session("session1")
        self.assertTrue(result)
        self.assertEqual(len(self.memory.list_sessions()), 0)

    def test_session_list(self):
        """测试列出所有会话。"""
        self.memory.save_session("s1", [])
        self.memory.save_session("s2", [])
        sessions = self.memory.list_sessions()
        self.assertEqual(len(sessions), 2)
        self.assertIn("s1", sessions)

    def test_to_dict_from_dict(self):
        """测试序列化和反序列化。"""
        self.memory.learn("Q1", "A1")
        self.memory.save_session("s1", [("user", "hi")])

        data = self.memory.to_dict()
        self.assertIn("memories", data)
        self.assertIn("sessions", data)
        self.assertIn("metadata", data)

        new_memory = MemoryStore()
        new_memory.from_dict(data)
        self.assertEqual(len(new_memory), 1)
        self.assertEqual(new_memory.session_count, 1)

    def test_to_json_from_json(self):
        """测试 JSON 序列化。"""
        self.memory.learn("Q1", "A1")
        json_str = self.memory.to_json()
        self.assertIsInstance(json_str, str)

        new_memory = MemoryStore()
        new_memory.from_json(json_str)
        self.assertEqual(len(new_memory), 1)

    def test_save_to_file_load_from_file(self):
        """测试文件持久化。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test_memory.json")
            self.memory.learn("Q1", "A1")
            self.memory.save_to_file(filepath)

            new_memory = MemoryStore()
            new_memory.load_from_file(filepath)
            self.assertEqual(len(new_memory), 1)

    def test_auto_save(self):
        """测试自动保存功能。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "auto_save.json")
            memory = MemoryStore(auto_save_path=filepath)
            memory.learn("Q1", "A1")

            # 检查文件是否自动创建
            self.assertTrue(os.path.exists(filepath))

    def test_len_and_total_answers(self):
        """测试统计属性。"""
        self.memory.learn("Q1", "A1")
        self.memory.learn("Q1", "A2")
        self.memory.learn("Q2", "B1")
        self.assertEqual(len(self.memory), 2)
        self.assertEqual(self.memory.total_answers, 3)

    def test_thread_safety(self):
        """测试线程安全（基本检查）。"""
        import threading

        def learn_questions(thread_id):
            for i in range(10):
                self.memory.learn(f"Q{thread_id}_{i}", f"A{thread_id}_{i}")

        threads = [threading.Thread(target=learn_questions, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 应该学到 50 个唯一的问题
        self.assertEqual(len(self.memory), 50)


if __name__ == "__main__":
    unittest.main()
