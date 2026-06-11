"""扩展层核心框架。

提供 Provider 标准接口、规范化器和路由调度器。
"""

from extensions.core.base_provider import DataProvider
from extensions.core.dispatcher import DataDispatcher
from extensions.core.normalizer import normalize

__all__ = ["DataProvider", "DataDispatcher", "normalize"]
