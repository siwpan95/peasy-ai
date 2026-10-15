"""
匹配器注册表 — 对标 ComfyUI 的 NODE_CLASS_MAPPINGS。

通过 @register_matcher 装饰器，任何模块都可以把自己的匹配器注册到全局表。
管道通过注册表自动发现和实例化匹配器，无需硬编码。

用法：
    from ai.matchers.registry import register_matcher, MATCHER_REGISTRY

    @register_matcher("my_custom")
    class MyCustomMatcher(BaseMatcher):
        ...

第三方模块可以：
    from easy_ai.matchers.registry import register_matcher
    @register_matcher("awesome_matcher")
    class AwesomeMatcher(BaseMatcher): ...
"""

from typing import Dict, Type
from .base import BaseMatcher

# 全局匹配器注册表：名称 → 类
MATCHER_REGISTRY: Dict[str, Type[BaseMatcher]] = {}


def register_matcher(name: str):
    """装饰器：将匹配器类注册到全局表。

    Args:
        name: 注册名称，与配置文件 matchers.{name}.enabled 对应。

    Returns:
        装饰器函数。

    Example:
        @register_matcher("regex")
        class RegexMatcher(BaseMatcher):
            ...
    """
    def decorator(cls: Type[BaseMatcher]) -> Type[BaseMatcher]:
        MATCHER_REGISTRY[name] = cls
        return cls
    return decorator


def get_registered_matchers() -> Dict[str, Type[BaseMatcher]]:
    """返回已注册的匹配器列表（只读副本）。"""
    return dict(MATCHER_REGISTRY)


def discover_and_register():
    """自动发现并注册内置匹配器（确保它们在 MATCHER_REGISTRY 中）。

    通过导入内置匹配器模块来触发 @register_matcher 装饰器。
    外部/第三方模块在 import 时自动触发注册。
    """
    # 触发导入以激活装饰器注册
    from . import regex_matcher  # noqa: F401
    from . import fuzzy_matcher  # noqa: F401
    from . import markov_chain   # noqa: F401
    from . import neural_matcher  # noqa: F401
