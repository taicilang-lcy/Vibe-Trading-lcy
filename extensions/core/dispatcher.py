"""数据路由调度器。

按数据类型路由到对应 Provider，支持降级链。
根据 config.yaml 配置的优先级依次尝试 Provider。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

# yaml 是可选依赖，用于加载 config.yaml
try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

from extensions.core.base_provider import (
    DataProvider,
    NoAvailableProviderError,
    DataFetchError,
)
from extensions.core.normalizer import normalize

logger = logging.getLogger(__name__)

# 默认配置文件路径
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


class DataDispatcher:
    """数据路由调度器。

    功能：
    1. 加载 config.yaml 配置
    2. 按数据类型路由到对应 Provider
    3. 支持降级链（依次尝试直到成功）
    4. 自动规范化返回数据
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        """初始化调度器。

        Args:
            config_path: 配置文件路径，默认为 extensions/config.yaml
        """
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self.config: dict[str, Any] = {}
        self.providers: dict[str, DataProvider] = {}
        self.type_routing: dict[str, list[str]] = {}

        self._load_config()
        self._init_providers()

    def _load_config(self) -> None:
        """加载配置文件。"""
        if not self.config_path.exists():
            logger.warning(
                "Config file not found at %s, using defaults",
                self.config_path
            )
            self.config = self._default_config()
        else:
            try:
                if yaml is None:
                    logger.warning(
                        "PyYAML not installed, cannot load config from %s, using defaults",
                        self.config_path
                    )
                    self.config = self._default_config()
                else:
                    with open(self.config_path, encoding="utf-8") as f:
                        self.config = yaml.safe_load(f) or {}
            except Exception as exc:
                logger.warning(
                    "Failed to load config from %s: %s, using defaults",
                    self.config_path, exc
                )
                self.config = self._default_config()

        # 解析数据类型路由
        self.type_routing = self.config.get("data_type_routing", {})

    def _default_config(self) -> dict[str, Any]:
        """返回默认配置。"""
        return {
            "providers": {
                "tushare_extended": {
                    "enabled": True,
                    "priority": 1,
                },
            },
            "data_type_routing": {
                "moneyflow": ["tushare_extended"],
                "limit_board": ["tushare_extended"],
                "dragon_tiger": ["tushare_extended"],
                "margin": ["tushare_extended"],
                "block_trade": ["tushare_extended"],
                "shareholders": ["tushare_extended"],
                "adj_factor": ["tushare_extended"],
            },
            "normalization": {
                "volume_unit": "shares",
                "amount_unit": "cny",
                "market_cap_unit": "yi_cny",
            },
        }

    def _init_providers(self) -> None:
        """初始化 Provider 实例。"""
        provider_configs = self.config.get("providers", {})

        # 延迟导入，避免循环依赖
        for name, cfg in provider_configs.items():
            if not cfg.get("enabled", True):
                continue

            try:
                provider = self._create_provider(name, cfg)
                if provider is not None:
                    self.providers[name] = provider
                    logger.info("Initialized provider: %s", name)
            except Exception as exc:
                logger.warning("Failed to initialize provider %s: %s", name, exc)

    def _create_provider(
        self, name: str, cfg: dict[str, Any]
    ) -> DataProvider | None:
        """创建 Provider 实例。

        Args:
            name: Provider 名称
            cfg: Provider 配置

        Returns:
            Provider 实例，或 None（如果不可用）
        """
        if name == "tushare_extended":
            from extensions.providers.tushare_extended.provider import (
                TushareExtendedProvider,
            )
            return TushareExtendedProvider(config=cfg)
        # 未来扩展其他 Provider
        # elif name == "astockdata":
        #     from extensions.providers.astockdata.provider import AstockDataProvider
        #     return AstockDataProvider(config=cfg)
        return None

    def fetch(
        self,
        data_type: str,
        *,
        apply_normalization: bool = True,
        **kwargs,
    ) -> pd.DataFrame:
        """获取数据。

        按降级链依次尝试 Provider，返回规范化后的 DataFrame。

        Args:
            data_type: 数据类型（如 'moneyflow', 'limit_board'）
            apply_normalization: 是否应用规范化（默认 True）
            **kwargs: 传递给 Provider.fetch() 的参数

        Returns:
            规范化后的 DataFrame

        Raises:
            NoAvailableProviderError: 所有 Provider 都不可用
        """
        provider_names = self.type_routing.get(data_type, [])
        if not provider_names:
            raise NoAvailableProviderError(
                f"No routing configured for data_type: {data_type}"
            )

        errors: list[str] = []

        for name in provider_names:
            provider = self.providers.get(name)
            if provider is None:
                logger.debug("Provider %s not initialized, skipping", name)
                continue

            if not provider.is_available():
                logger.debug("Provider %s not available, skipping", name)
                continue

            try:
                logger.debug(
                    "Fetching %s from provider %s with kwargs: %s",
                    data_type, name, kwargs
                )
                df = provider.fetch(data_type, **kwargs)

                if df is not None and not df.empty:
                    if apply_normalization:
                        df = normalize(df, source=name)
                    logger.info(
                        "Successfully fetched %s rows from %s.%s",
                        len(df), name, data_type
                    )
                    return df

            except Exception as exc:
                errors.append(f"{name}: {exc}")
                logger.warning(
                    "Provider %s failed for %s: %s",
                    name, data_type, exc
                )
                continue

        raise NoAvailableProviderError(
            f"All providers failed for {data_type}. Errors: {'; '.join(errors)}"
        )

    def list_types(self) -> list[str]:
        """列出所有支持的数据类型。"""
        return list(self.type_routing.keys())

    def list_providers(self) -> list[str]:
        """列出所有已初始化的 Provider。"""
        return list(self.providers.keys())

    def get_provider(self, name: str) -> DataProvider | None:
        """按名称获取 Provider。"""
        return self.providers.get(name)


# 全局单例
_dispatcher: DataDispatcher | None = None


def get_dispatcher(config_path: str | Path | None = None) -> DataDispatcher:
    """获取全局调度器实例。

    Args:
        config_path: 配置文件路径（可选）

    Returns:
        DataDispatcher 实例
    """
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = DataDispatcher(config_path=config_path)
    return _dispatcher


def fetch(data_type: str, **kwargs) -> pd.DataFrame:
    """便捷函数：通过全局调度器获取数据。

    Args:
        data_type: 数据类型
        **kwargs: 传递给 Provider 的参数

    Returns:
        DataFrame
    """
    return get_dispatcher().fetch(data_type, **kwargs)