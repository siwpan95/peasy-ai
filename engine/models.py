"""
数据模型：Scene、Option、GameState。

所有字段名来自 JSON，代码零硬编码。
属性名（如 army/religion/people/treasure）由 config.json 决定，
引擎只操作字典，不预设任何属性名。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class Option:
    """一个选择项。"""
    text: str
    effects: Dict[str, int] = field(default_factory=dict)
    condition: Optional[Dict[str, Any]] = None
    next: str = ""
    flag: Optional[str] = None
    give_clue: Optional[str] = None


@dataclass
class Scene:
    """一个场景（对话节点）。"""
    id: str
    speaker: str = ""
    text: str = ""
    options: List[Option] = field(default_factory=list)
    # 可选扩展字段
    bgm: Optional[str] = None
    sfx: Optional[str] = None


@dataclass
class GameState:
    """游戏运行状态。"""
    current_scene_id: str = ""
    attributes: Dict[str, int] = field(default_factory=dict)
    flags: set = field(default_factory=set)
    clues: set = field(default_factory=set)
    ending_triggered: Optional[str] = None
    # 存档用额外信息
    turn_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_scene_id": self.current_scene_id,
            "attributes": dict(self.attributes),
            "flags": list(self.flags),
            "clues": list(self.clues),
            "ending_triggered": self.ending_triggered,
            "turn_count": self.turn_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GameState":
        return cls(
            current_scene_id=data.get("current_scene_id", ""),
            attributes=data.get("attributes", {}),
            flags=set(data.get("flags", [])),
            clues=set(data.get("clues", [])),
            ending_triggered=data.get("ending_triggered"),
            turn_count=data.get("turn_count", 0),
        )
