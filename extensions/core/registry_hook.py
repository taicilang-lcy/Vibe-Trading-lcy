"""扩展层注册钩子。

用于将扩展层的 Provider 注册到 Vibe-Trading 的 Loader Registry。

设计原则：
- 零修改上游 agent/ 目录
- 通过 hook 动态注册扩展 Loader
- 只需在启动入口加 1 行 import

使用方式：
    # 在应用启动时（如 agent/__init__.py 或启动脚本）
    from extensions.core.registry_hook import register_extensions
    register_extensions()
"""

from __future__ import annotations

import logging
from typing import Any

from extensions.core.base_provider import DataProvider, ProviderRegistry
from extensions.core.dispatcher import DataDispatcher, get_dispatcher

logger = logging.getLogger(__name__)

# 全局扩展层注册中心
_extension_registry = ProviderRegistry()


def register_extensions() -> ProviderRegistry:
    """注册所有扩展层 Provider。

    此函数应在应用启动时调用一次。

    Returns:
        ProviderRegistry 实例

    Example:
        >>> from extensions.core.registry_hook import register_extensions
        >>> registry = register_extensions()
        >>> registry.list_all()
        ['tushare_extended']
    """
    dispatcher = get_dispatcher()

    # 将调度器中的 Provider 注册到扩展层注册中心
    for name, provider in dispatcher.providers.items():
        _extension_registry.register(provider)
        logger.info("Registered extension provider: %s", name)

    return _extension_registry


def get_extension_registry() -> ProviderRegistry:
    """获取扩展层注册中心。

    Returns:
        ProviderRegistry 实例
    """
    return _extension_registry


# -------------------------------------------------------------------------
# Loader 适配器（用于兼容 Vibe-Trading 的 DataLoader 协议）
# -------------------------------------------------------------------------

class ExtensionLoaderAdapter:
    """扩展 Provider 到 DataLoader 协议的适配器。

    Vibe-Trading 的 Loader Registry 使用 DataLoader 协议，
    此适配器将扩展层 Provider 转换为符合该协议的 Loader。
    """

    name: str
    markets: set[str]
    requires_auth: bool

    def __init__(self, provider: DataProvider) -> None:
        """初始化适配器。

        Args:
            provider: 扩展层 Provider 实例
        """
        self._provider = provider
        self.name = f"ext_{provider.name}"
        self.markets = {"a_share"}  # 扩展层目前只支持 A 股
        self.requires_auth = True  # 大部分扩展需要 token

    def is_available(self) -> bool:
        """检查 Provider 是否可用。"""
        return self._provider.is_available()

    def fetch(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """获取数据（兼容 DataLoader 协议）。

        注意：扩展层主要用于特殊数据类型（资金流、龙虎榜等），
        与 K 线 Loader 的接口不完全一致，此方法主要用于兼容。

        Args:
            codes: 股票代码列表
            start_date: 开始日期
            end_date: 结束日期
            interval: 时间间隔（扩展层大多忽略此参数）
            fields: 字段列表（用于确定数据类型）

        Returns:
            {stock_code: DataFrame} 映射
        """
        # 根据 fields 推断数据类型
        # 这是一个简化实现，实际使用时可能需要更复杂的映射
        data_type = self._infer_data_type(fields)

        if data_type is None:
            logger.warning(
                "Cannot infer data_type from fields=%s, using default",
                fields
            )
            return {}

        try:
            df = self._provider.fetch(
                data_type,
                codes=codes,
                start_date=start_date,
                end_date=end_date,
            )

            if df is None or df.empty:
                return {}

            # 转换为 {stock_code: DataFrame} 格式
            result: dict[str, Any] = {}
            if "stock_code" in df.columns:
                for code in codes:
                    stock_df = df[df["stock_code"] == code]
                    if not stock_df.empty:
                        result[code] = stock_df

            return result

        except Exception as exc:
            logger.error(
                "ExtensionLoaderAdapter.fetch failed: %s",
                exc
            )
            return {}

    def _infer_data_type(self, fields: list[str] | None) -> str | None:
        """从字段推断数据类型。"""
        if not fields:
            return None

        # 简单的字段 → 数据类型映射
        field_to_type = {
            "net_mf_amount": "moneyflow",
            "up_stat": "limit_board",
            "exalter": "dragon_tiger",
            "rzye": "margin",
            "trade_price": "block_trade",
            "holder_num": "shareholders",
            "adj_factor": "adj_factor",
        }

        for field in fields or []:
            if field in field_to_type:
                return field_to_type[field]

        return None


def create_loader_adapters() -> list[ExtensionLoaderAdapter]:
    """为所有已注册的 Provider 创建 Loader 适配器。

    Returns:
        ExtensionLoaderAdapter 列表
    """
    adapters = []
    registry = get_extension_registry()

    for name in registry.list_all():
        provider = registry.get(name)
        if provider:
            adapter = ExtensionLoaderAdapter(provider)
            adapters.append(adapter)

    return adapters


def inject_into_loader_registry() -> None:
    """将扩展层 Loader 注入到 Vibe-Trading 的 Loader Registry。

    注意：此函数需要在 backtest.loaders.registry 模块加载后调用，
    且仅用于高级用例。一般情况下，建议使用独立的扩展层 API。
    """
    try:
        from backtest.loaders.registry import LOADER_REGISTRY, register

        adapters = create_loader_adapters()
        for adapter in adapters:
            if adapter.name not in LOADER_REGISTRY:
                register(adapter.__class__)
                LOADER_REGISTRY[adapter.name] = adapter.__class__
                logger.info(
                    "Injected extension loader into LOADER_REGISTRY: %s",
                    adapter.name
                )

    except ImportError:
        logger.warning(
            "backtest.loaders.registry not available, "
            "skipping loader registry injection"
        )