"""
响应器注册表 — 对标 ComfyUI 的 NODE_CLASS_MAPPINGS。

通过 @register_responder 装饰器注册专用响应器。
管道通过注册表自动发现和实例化，无需硬编码。

用法：
    from easy_ai.ai.responders.registry import register_responder, RESPONDER_REGISTRY

    @register_responder("time")
    class TimeResponder:
        ...
"""

from typing import Dict, Type, Any

# 全局响应器注册表：名称 → 类
# 值可以是任何带 process(text) -> Optional[str] 接口的类
RESPONDER_REGISTRY: Dict[str, Type] = {}


def register_responder(name: str):
    """装饰器：将响应器类注册到全局表。

    Args:
        name: 注册名称，与配置文件 responders.{name} 对应。

    Example:
        @register_responder("time")
        class TimeResponder:
            ...
    """
    def decorator(cls: Type) -> Type:
        RESPONDER_REGISTRY[name] = cls
        return cls
    return decorator


def get_registered_responders() -> Dict[str, Type]:
    """返回已注册的响应器列表（只读副本）。"""
    return dict(RESPONDER_REGISTRY)
