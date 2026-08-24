"""
单元测试：AICore

测试覆盖：
- 初始化
- respond / respond_async
- 学习/遗忘
- 会话管理
- 规则管理
- 存档/读档
- 热重载
"""

import unittest
import tempfile
import os
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from ai.core import AICore, create, from_dict


class TestAICore(unittest.TestCase):
    """AICore 单元测试。"""

    def setUp(self):
        """每个测试前的设置。"""
        # 使用最小配置
        self.minimal_config = {
            "name": "test",
            "rules": [
                {
                    "pattern": "你好",
                    "responses": ["你好呀！"],
                    "confidence": 0.95
                },
                {
                    "pattern": ".*",
                    "responses": ["我不懂"],
                    "confidence": 0.01
                }
            ]
        }
        self.ai = from_dict(self.minimal_config)

    def test_initialization(self):
        """测试初始化。"""
        self.assertEqual(self.ai.name, "test")
        self.assertIsNotNone(self.ai.memory)
        self.assertIsNotNone(self.ai.pipeline)

    def test_respond(self):
        """测试基本对话。"""
        reply = self.ai.respond("你好")
        self.assertEqual(reply, "你好呀！")

    def test_respond_fallback(self):
        """测试兜底回复。"""
        reply = self.ai.respond("随便说点什么")
        self.assertEqual(reply, "我不懂")

    def test_respond_async(self):
        """测试异步对话。"""
        import asyncio
        reply = asyncio.run(self.ai.respond_async("你好"))
        self.assertEqual(reply, "你好呀！")

    def test_learn(self):
        """测试学习功能。"""
        result = self.ai.learn("自定义问题", "自定义回答")
        self.assertTrue(result)
        self.assertEqual(self.ai.memory_count, 1)

    def test_forget(self):
        """测试遗忘功能。"""
        self.ai.learn("Q1", "A1")
        result = self.ai.forget("Q1")
        self.assertTrue(result)
        self.assertEqual(self.ai.memory_count, 0)

    def test_chat_session(self):
        """测试会话式聊天。"""
        reply1 = self.ai.chat("user1", "你好")
        self.assertEqual(reply1, "你好呀！")

        # 检查会话是否创建
        self.assertIsNotNone(self.ai.session)

    def test_add_rule(self):
        """测试动态添加规则。"""
        initial_count = len(self.ai.config.data.get("rules", []))
        self.ai.add_rule("测试", ["测试回复"])
        new_count = len(self.ai.config.data.get("rules", []))
        self.assertEqual(new_count, initial_count + 1)

    def test_remove_rule(self):
        """测试删除规则。"""
        self.ai.add_rule("测试", ["测试回复"])
        result = self.ai.remove_rule("测试")
        self.assertTrue(result)

    def test_save_load(self):
        """测试存档和读档。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test_memory.json")
            self.ai.learn("Q1", "A1")
            self.ai.save(filepath)

            new_ai = from_dict(self.minimal_config)
            new_ai.load(filepath)
            self.assertEqual(new_ai.memory_count, 1)

    def test_export_import_state(self):
        """测试导出导入状态。"""
        self.ai.learn("Q1", "A1")
        state = self.ai.export_state()

        new_ai = from_dict(self.minimal_config)
        new_ai.import_state(state)
        self.assertEqual(new_ai.memory_count, 1)

    def test_reload(self):
        """测试热重载。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self.minimal_config, f)

            ai = AICore(config_path)
            ai.reload()  # 应该不报错
            self.assertEqual(ai.name, "test")

    def test_enable_sessions(self):
        """测试启用会话管理。"""
        self.ai.enable_sessions(max_history=5, ttl_minutes=10)
        self.assertIsNotNone(self.ai.session)

    def test_enable_intent(self):
        """测试启用意图识别。"""
        self.ai.enable_intent()
        self.assertIsNotNone(self.ai.intent_clf)

    def test_set_safety(self):
        """测试设置安全过滤。"""
        self.ai.set_safety(["暴力", "色情"])
        # 应该不报错

    def test_set_selection_strategy(self):
        """测试设置响应策略。"""
        self.ai.set_selection_strategy("random")
        # 应该不报错

    def test_get_info(self):
        """测试获取信息。"""
        info = self.ai.get_info()
        self.assertIn("version", info)
        self.assertIn("name", info)
        self.assertIn("memory_count", info)

    def test_create_function(self):
        """测试 create 便捷函数。"""
        ai = create(config_path=None)
        self.assertIsNotNone(ai)

    def test_from_dict_function(self):
        """测试 from_dict 便捷函数。"""
        ai = from_dict(self.minimal_config)
        self.assertEqual(ai.name, "test")

    def test_respond_with_empty_message(self):
        """测试空消息处理。"""
        reply = self.ai.respond("")
        self.assertIsNotNone(reply)

    def test_respond_with_none(self):
        """测试 None 消息处理。"""
        reply = self.ai.respond(None)
        self.assertIsNotNone(reply)


if __name__ == "__main__":
    unittest.main()
