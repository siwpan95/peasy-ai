"""
数据加载器：从 JSON 文件构建所有游戏数据。

支持的目录结构（都在配置中指定，代码不硬编码路径）：
- config.json     → 全局配置（属性定义、结局、起始场景）
- characters.json → 角色信息（名称、头像、立绘）
- scenes/*.json   → 场景库（对话、选项、条件、效果）
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Any, Optional

from .models import Scene, Option


class DataLoader:
    """加载并缓存 JSON 数据。"""

    def __init__(self, data_path: str = "data"):
        """
        Args:
            data_path: JSON 数据根目录。
        """
        self.data_path = Path(data_path)
        self.config: Dict[str, Any] = {}
        self.characters: Dict[str, Dict[str, Any]] = {}
        self.scenes: Dict[str, Scene] = {}
        self._loaded = False

    def load(self, config_file: str = "config.json"):
        """加载全部数据。"""
        self._load_config(config_file)
        self._load_characters()
        self._load_scenes()
        self._loaded = True

    # ============================================================
    # 配置
    # ============================================================
    def _load_config(self, filename: str):
        path = self.data_path / filename
        if path.exists():
            self.config = self._read_json(path)
        else:
            self.config = self._default_config()

    @staticmethod
    def _default_config() -> Dict[str, Any]:
        return {
            "title": "未命名故事",
            "attributes": [],
            "attribute_default": 50,
            "attribute_max": 100,
            "attribute_min": 0,
            "start_scene": "start",
            "endings": {},
        }

    # ============================================================
    # 角色
    # ============================================================
    def _load_characters(self):
        path = self.data_path / "characters.json"
        if path.exists():
            self.characters = self._read_json(path)
        else:
            self.characters = {}

    def get_character(self, speaker_id: str) -> Dict[str, Any]:
        """获取角色信息。"""
        return self.characters.get(speaker_id, {
            "name": speaker_id,
            "avatar": None,
        })

    # ============================================================
    # 场景
    # ============================================================
    def _load_scenes(self):
        """加载 scenes/ 目录下的所有 JSON 文件。"""
        scenes_dir = self.data_path / "scenes"
        if not scenes_dir.exists():
            return

        for file in sorted(scenes_dir.glob("*.json")):
            data = self._read_json(file)
            scene = self._parse_scene(data)
            if scene:
                self.scenes[scene.id] = scene

    def _parse_scene(self, data: Dict) -> Optional[Scene]:
        """从 JSON 构建 Scene 对象。"""
        options = []
        for opt_data in data.get("options", []):
            option = Option(
                text=opt_data.get("text", ""),
                effects=opt_data.get("effects", {}),
                condition=opt_data.get("condition"),
                next=opt_data.get("next", ""),
                flag=opt_data.get("flag"),
                give_clue=opt_data.get("give_clue"),
            )
            options.append(option)

        return Scene(
            id=data.get("id", ""),
            speaker=data.get("speaker", ""),
            text=data.get("text", ""),
            options=options,
            bgm=data.get("bgm"),
            sfx=data.get("sfx"),
        )

    # ============================================================
    # 工具
    # ============================================================
    @staticmethod
    def _read_json(path: Path) -> Any:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_attributes(self) -> List[str]:
        return self.config.get("attributes", [])

    def get_attribute_default(self) -> int:
        return self.config.get("attribute_default", 50)

    def get_start_scene(self) -> str:
        return self.config.get("start_scene", "start")

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def title(self) -> str:
        return self.config.get("title", "未命名")
