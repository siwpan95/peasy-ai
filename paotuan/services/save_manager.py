# -*- coding: utf-8 -*-
"""
迷失之镜 — 存档管理器 (Model 层 · 阶段 2)
跑团行为存档：角色卡引用 + 运行时状态 + 游戏进度 + flags + 选择历史
"""
import json
import os
import time
from typing import Dict, List, Optional
from core.character import Character

# 项目根目录（pt/）
_PT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SaveManager:
    """存档管理器"""

    def __init__(self, saves_dir: str = None):
        if saves_dir is None:
            saves_dir = os.path.join(_PT_DIR, "saves")
        self.saves_dir = saves_dir
        os.makedirs(saves_dir, exist_ok=True)

    def save(self, save_name: str, pc: Character, game_progress: Dict) -> str:
        """
        保存游戏
        返回存档文件路径
        """
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{save_name}_{timestamp}.json"
        filepath = os.path.join(self.saves_dir, filename)

        save_data = {
            "save_name": save_name,
            "timestamp": timestamp,
            "character_id": pc.character_id,
            "character_name": pc.name,
            "character_state": pc.create_snapshot(),
            "game_progress": game_progress,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)

        return filepath

    def load(self, filepath: str) -> Optional[Dict]:
        """加载存档"""
        if not os.path.exists(filepath):
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_saves(self) -> List[Dict]:
        """列出所有存档"""
        saves = []
        if not os.path.exists(self.saves_dir):
            return saves

        for filename in sorted(os.listdir(self.saves_dir), reverse=True):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(self.saves_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                saves.append({
                    "filename": filename,
                    "path": filepath,
                    "save_name": data.get("save_name", ""),
                    "timestamp": data.get("timestamp", ""),
                    "character_name": data.get("character_name", ""),
                })
            except Exception:
                continue
        return saves

    def load_newest(self, module_id: str) -> Optional[Dict]:
        """加载指定模组的最新存档"""
        saves = self.list_saves()
        for s in saves:
            if module_id in s.get("save_name", ""):
                return self.load(s["path"])
        return None

    def delete_save(self, filepath: str) -> bool:
        """删除存档"""
        if os.path.exists(filepath):
            os.remove(filepath)
            return True
        return False
