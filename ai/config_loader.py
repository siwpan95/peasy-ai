"""
配置加载器：从 JSON 文件加载所有 AI 行为配置。
零硬编码 —— 规则的格式、安全词、回复模板全在配置文件中定义。

支持 schema 版本化：配置文件包含 schema_version 字段，
加载时自动执行迁移（对标 ComfyUI API 版本机制）。
"""

import json
import logging
import os
from typing import Dict, List, Any, Optional, Callable

logger = logging.getLogger(__name__)

# schema 迁移表：旧版本 → (新版本号, 迁移函数)
SCHEMA_MIGRATIONS: Dict[str, Callable[[Dict], Dict]] = {
    # 示例：未来从 1.0 升级到 2.0 时的迁移逻辑
    # "1.0": _migrate_1_to_2,
}


class ConfigLoader:
    """加载并校验 AI 配置文件。"""

    CURRENT_SCHEMA_VERSION = "1.0"

    def __init__(self, config_path: Optional[str] = None):
        """
        Args:
            config_path: JSON 配置文件路径。为 None 时使用内置最小默认配置。
        """
        self.config_path = config_path
        self.data: Dict[str, Any] = {}

        if config_path and os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
            self._migrate_schema()
        else:
            self.data = self._default_config()

        self._validate()

    # ============================================================
    # Schema 迁移
    # ============================================================
    def _migrate_schema(self):
        """将配置文件升级到最新 schema 版本。"""
        version = self.data.get("schema_version", "0.0")
        while version in SCHEMA_MIGRATIONS:
            logger.info("配置迁移：%s → %s（%s）",
                        version, SCHEMA_MIGRATIONS, self.config_path)
            migrate_fn = SCHEMA_MIGRATIONS[version]
            self.data = migrate_fn(self.data)
            version = self.data.get("schema_version", "0.0")

        self.data["schema_version"] = self.CURRENT_SCHEMA_VERSION
    # --- 结束 _migrate_schema ---

    # ============================================================
    # 默认配置（最小化，零领域知识）
    # ============================================================
    @staticmethod
    def _default_config() -> Dict[str, Any]:
        return {
            "schema_version": "1.0",
            "name": "easy-ai",
            "version": "2.2.0",

            # 安全过滤器
            "safety": {
                "enabled": True,
                "keywords": [],
                "response": [
                    "抱歉，我无法回答这个问题。",
                    "这个话题我不太了解，换个话题吧？"
                ]
            },

            # 规则匹配（正则模式 → 回复列表）
            "rules": [
                {"pattern": "你好|嗨|hello|hi", "responses": ["你好呀！", "嗨！有什么可以帮你的？"]},
                {"pattern": "谢谢|多谢|感谢", "responses": ["不客气！", "能帮到你就好。"]},
                {"pattern": "再见|拜拜|bye", "responses": ["再见！", "下次见～"]},
                {"pattern": ".*", "responses": [
                    "这个话题很有意思，能再详细说说吗？",
                    "嗯，我在听。",
                    "不太确定该怎么回应，但你可以教我。"
                ]}
            ],

            # 匹配器配置
            "matchers": {
                "regex": {"enabled": True, "priority": 10},
                "fuzzy": {"enabled": True, "priority": 20, "threshold": 0.3}
            },

            # 代词反射规则
            "reflections": {
                "我": "你", "你": "我",
                "我的": "你的", "你的": "我的",
                "我是": "你是", "你是": "我是"
            },

            # 空消息回复
            "empty_input_response": "请说点什么吧。",

            # 最终兜底回复
            "fallback_response": "我不太明白，你能换个方式说吗？"
        }

    # ============================================================
    # 校验
    # ============================================================
    def _validate(self):
        """保证配置数据结构合法。"""
        if "rules" not in self.data:
            self.data["rules"] = [{"pattern": ".*", "responses": ["我不太明白。"]}]

        if "safety" not in self.data:
            self.data["safety"] = {"enabled": False, "keywords": [], "response": ["抱歉。"]}

        if "matchers" not in self.data:
            self.data["matchers"] = {"regex": {"enabled": True, "priority": 10}}

    def validate(self) -> List[str]:
        """完整校验配置，返回错误列表。

        Returns:
            错误描述列表，空列表表示配置有效。

        检查内容：
        - 每条规则必须有 pattern 和 responses
        - pattern 不能为空
        - responses 不能为空列表
        """
        errors = []
        for i, rule in enumerate(self.data.get("rules", [])):
            if not isinstance(rule, dict):
                errors.append(f"rules[{i}] 不是字典类型")
                continue
            if "pattern" not in rule:
                errors.append(f"rules[{i}] 缺少 pattern 字段")
            elif not rule["pattern"]:
                errors.append(f"rules[{i}] pattern 不能为空")
            if "responses" not in rule:
                errors.append(f"rules[{i}] 缺少 responses 字段")
            elif not rule["responses"]:
                errors.append(f"rules[{i}] responses 不能为空列表")

        if errors:
            logger.warning("配置校验发现 %d 个问题", len(errors))
            for e in errors[:5]:  # 最多显示前 5 个
                logger.warning("  - %s", e)
        return errors

    # ============================================================
    # 便捷访问
    # ============================================================
    def get_rules(self) -> List[Dict[str, Any]]:
        return self.data.get("rules", [])

    def get_safety(self) -> Dict[str, Any]:
        return self.data.get("safety", {})

    def get_matchers(self) -> Dict[str, Any]:
        return self.data.get("matchers", {})

    def get_reflections(self) -> Dict[str, str]:
        return self.data.get("reflections", {})

    @property
    def empty_input_response(self) -> str:
        return self.data.get("empty_input_response", "请说点什么。")

    @property
    def fallback_response(self) -> str:
        return self.data.get("fallback_response", "我不太明白。")

    @property
    def name(self) -> str:
        return self.data.get("name", "easy-ai")

    def __repr__(self):
        return f"<ConfigLoader name='{self.name}' rules={len(self.get_rules())}>"
