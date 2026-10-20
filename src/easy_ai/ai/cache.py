"""
响应缓存 — 对标 ComfyUI 的多策略缓存系统。

避免高频确定性查询（如"今天几号"）每次都走完整匹配器链。

策略：
- NoCache: 关闭缓存（默认，零开销）
- LRUCache: 最近最少使用淘汰，适合通用场景
- TTLCache: 带过期时间，适合"今天几号"类时效查询

用法：
    from easy_ai.ai.cache import LRUCache, NoCache

    ai = AICore(cache=LRUCache(max_size=500))
    # 或
    ai = AICore(cache=NoCache())  # 默认
"""

from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Any, Optional
import time


class ResponseCache(ABC):
    """缓存抽象基类。"""

    @abstractmethod
    def get(self, key: str) -> Optional[str]:
        """从缓存获取值，未命中返回 None。"""
        ...

    @abstractmethod
    def put(self, key: str, value: str):
        """将值放入缓存。"""
        ...

    @abstractmethod
    def clear(self):
        """清空所有缓存。"""
        ...

    @abstractmethod
    def size(self) -> int:
        """返回缓存条目数。"""
        ...


class NoCache(ResponseCache):
    """关闭缓存（默认策略）。"""

    def get(self, key: str) -> Optional[str]:
        return None

    def put(self, key: str, value: str):
        pass

    def clear(self):
        pass

    def size(self) -> int:
        return 0


class LRUCache(ResponseCache):
    """最近最少使用（LRU）缓存。

    适合通用对话场景，保留最常使用的回复。
    """

    def __init__(self, max_size: int = 500):
        self._cache = OrderedDict()
        self._max_size = max_size

    def get(self, key: str) -> Optional[str]:
        if key in self._cache:
            # 命中时移到末尾（标记为最近使用）
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, key: str, value: str):
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = value
        # 淘汰最旧的
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def clear(self):
        self._cache.clear()

    def size(self) -> int:
        return len(self._cache)


class TTLCache(ResponseCache):
    """带过期时间的缓存。

    适合"今天几号"等时效性查询：到时间自动失效。
    """

    def __init__(self, ttl_seconds: float = 60.0, max_size: int = 1000):
        self._cache = OrderedDict()
        self._ttl = ttl_seconds
        self._max_size = max_size

    def _clean_expired(self):
        """清理过期条目。"""
        now = time.time()
        expired = [k for k, (_, ts) in self._cache.items()
                   if now - ts > self._ttl]
        for k in expired:
            del self._cache[k]

    def get(self, key: str) -> Optional[str]:
        self._clean_expired()
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp <= self._ttl:
                self._cache.move_to_end(key)
                return value
            else:
                del self._cache[key]
        return None

    def put(self, key: str, value: str):
        self._clean_expired()
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = (value, time.time())
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def clear(self):
        self._cache.clear()

    def size(self) -> int:
        self._clean_expired()
        return len(self._cache)
