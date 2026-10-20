"""
单元测试：NarrativeEngine

测试覆盖：
- 初始化
- 场景导航
- 选项执行
- 属性变化
- 结局触发
- 场景预览/跳转
- 撤销/重做
- 存档/读档
"""

import unittest
import tempfile
import os
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from easy_ai.engine.core import NarrativeEngine
from easy_ai.engine.models import GameState, Scene, Option


class TestNarrativeEngine(unittest.TestCase):
    """NarrativeEngine 单元测试。"""

    def setUp(self):
        """每个测试前的设置。"""
        # 使用项目内置的测试数据
        self.engine = NarrativeEngine(
            data_path=str(Path(__file__).resolve().parents[1] / "src" / "easy_ai" / "data"),
            config_file="config.json"
        )

    def test_initialization(self):
        """测试初始化。"""
        self.assertIsNotNone(self.engine.state)
        self.assertIsNotNone(self.engine.data)
        self.assertIsNotNone(self.engine.history)

    def test_get_current_scene(self):
        """测试获取当前场景。"""
        scene = self.engine.get_current_scene()
        self.assertIsNotNone(scene)
        self.assertEqual(scene.id, "prologue")

    def test_get_available_options(self):
        """测试获取可用选项。"""
        options = self.engine.get_available_options()
        self.assertGreater(len(options), 0)

    def test_choose_option(self):
        """测试选择选项。"""
        options = self.engine.get_available_options()
        if options:
            result = self.engine.choose_option(0)
            self.assertTrue(result)

    def test_attribute_changes(self):
        """测试属性变化。"""
        initial_attrs = self.engine.attributes.copy()
        options = self.engine.get_available_options()

        if options:
            option = options[0]
            if option.effects:
                result = self.engine.choose_option(0)
                self.assertTrue(result)

                # 检查属性是否变化
                new_attrs = self.engine.attributes
                for attr, delta in option.effects.items():
                    if attr in initial_attrs:
                        self.assertEqual(
                            new_attrs[attr],
                            initial_attrs[attr] + delta
                        )

    def test_scene_transition(self):
        """测试场景跳转。"""
        initial_scene = self.engine.current_scene_id
        options = self.engine.get_available_options()

        if options and not options[0].next.startswith("end_"):
            next_scene = options[0].next
            result = self.engine.choose_option(0)
            self.assertTrue(result)
            self.assertEqual(self.engine.current_scene_id, next_scene)
            self.assertNotEqual(self.engine.current_scene_id, initial_scene)

    def test_preview_option(self):
        """测试预览选项。"""
        options = self.engine.get_available_options()
        if options:
            result = self.engine.preview_option(0)
            if result:
                scene, effects = result
                self.assertIsNotNone(scene)

    def test_preview_scene(self):
        """测试预览场景。"""
        scene = self.engine.preview_scene("prologue")
        self.assertIsNotNone(scene)
        self.assertEqual(scene.id, "prologue")

    def test_preview_nonexistent_scene(self):
        """测试预览不存在的场景。"""
        scene = self.engine.preview_scene("nonexistent")
        self.assertIsNone(scene)

    def test_jump_to_scene(self):
        """测试跳转到场景。"""
        # 先确保游戏未结束
        if not self.engine.is_ended:
            result = self.engine.jump_to_scene("prologue")
            self.assertTrue(result)
            self.assertEqual(self.engine.current_scene_id, "prologue")

    def test_jump_to_nonexistent_scene(self):
        """测试跳转到不存在的场景。"""
        result = self.engine.jump_to_scene("nonexistent")
        self.assertFalse(result)

    def test_undo_redo(self):
        """测试撤销和重做。"""
        # 先执行一个选项
        options = self.engine.get_available_options()
        if options and not options[0].next.startswith("end_"):
            self.engine.choose_option(0)
            scene_after = self.engine.current_scene_id

            # 撤销
            if self.engine.can_undo():
                result = self.engine.undo()
                self.assertTrue(result)

                # 重做
                if self.engine.can_redo():
                    result = self.engine.redo()
                    self.assertTrue(result)
                    self.assertEqual(self.engine.current_scene_id, scene_after)

    def test_save_load(self):
        """测试存档和读档。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "save.json")

            # 执行一个选项
            options = self.engine.get_available_options()
            if options:
                self.engine.choose_option(0)

            # 保存
            self.engine.save(filepath)
            self.assertTrue(os.path.exists(filepath))

            # 加载到新引擎
            new_engine = NarrativeEngine(
                data_path=str(Path(__file__).resolve().parents[1] / "src" / "easy_ai" / "data"),
                config_file="config.json"
            )
            new_engine.load(filepath)

            # 验证状态一致
            self.assertEqual(
                new_engine.current_scene_id,
                self.engine.current_scene_id
            )

    def test_restart(self):
        """测试重新开始。"""
        # 执行一些操作
        options = self.engine.get_available_options()
        if options:
            self.engine.choose_option(0)

        # 重新开始
        self.engine.restart()
        self.assertEqual(self.engine.current_scene_id, "prologue")
        self.assertEqual(self.engine.turn_count, 0)

    def test_get_scene_list(self):
        """测试获取场景列表。"""
        scenes = self.engine.get_scene_list()
        self.assertIn("prologue", scenes)
        self.assertGreater(len(scenes), 0)

    def test_get_scene_info(self):
        """测试获取场景信息。"""
        info = self.engine.get_scene_info("prologue")
        self.assertIsNotNone(info)
        self.assertEqual(info["id"], "prologue")

    def test_get_stats(self):
        """测试获取统计信息。"""
        stats = self.engine.get_stats()
        self.assertIn("turn_count", stats)
        self.assertIn("current_scene", stats)
        self.assertIn("attributes", stats)
        self.assertIn("is_ended", stats)

    def test_ending_trigger(self):
        """测试结局触发。"""
        # 手动设置属性触顶
        attrs = self.engine.state.attributes
        max_val = self.engine.data.config.get("attribute_max", 100)

        for attr in attrs:
            attrs[attr] = max_val

        # 检查是否触发结局
        self.engine._check_attribute_endings()
        self.assertTrue(self.engine.is_ended)

    def test_listeners(self):
        """测试事件监听器。"""
        called = [False]

        def callback(engine):
            called[0] = True

        self.engine.add_listener(callback)
        options = self.engine.get_available_options()

        if options:
            self.engine.choose_option(0)
            self.assertTrue(called[0])

    def test_remove_listener(self):
        """测试移除监听器。"""
        def callback(engine):
            pass

        self.engine.add_listener(callback)
        self.engine.remove_listener(callback)
        # 应该不报错

    def test_can_undo_redo_initial(self):
        """测试初始状态下无法撤销/重做。"""
        self.assertFalse(self.engine.can_undo())
        self.assertFalse(self.engine.can_redo())


if __name__ == "__main__":
    unittest.main()
