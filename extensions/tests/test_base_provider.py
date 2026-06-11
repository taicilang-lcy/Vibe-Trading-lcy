"""测试 base_provider 模块。"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from extensions.core.base_provider import (
    DataProvider,
    DataProviderError,
    NoAvailableProviderError,
    DataFetchError,
    ProviderRegistry,
    DEFAULT_RATE_LIMIT_INTERVAL,
    DEFAULT_MAX_RETRIES,
)


class _FakeProvider(DataProvider):
    """测试用假 Provider。"""

    @property
    def name(self) -> str:
        return "fake"

    @property
    def description(self) -> str:
        return "Fake provider for testing"

    @property
    def supported_types(self) -> list[str]:
        return ["moneyflow", "limit_board"]

    def is_available(self) -> bool:
        return True

    def fetch(self, data_type: str, **kwargs) -> pd.DataFrame:
        return pd.DataFrame({"col": [1, 2, 3]})


class TestDataProvider:
    """DataProvider 基类测试。"""

    def test_provider_properties(self) -> None:
        """测试 Provider 基本属性。"""
        provider = _FakeProvider()
        assert provider.name == "fake"
        assert provider.description == "Fake provider for testing"
        assert "moneyflow" in provider.supported_types
        assert provider.is_available()

    def test_fetch_returns_dataframe(self) -> None:
        """测试 fetch 返回 DataFrame。"""
        provider = _FakeProvider()
        df = provider.fetch("moneyflow")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3

    def test_fetch_with_retry_transient_error(self, monkeypatch) -> None:
        """测试瞬态错误重试机制。"""
        provider = _FakeProvider()

        call_count = {"n": 0}

        def flaky_func(**kwargs):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise ConnectionError("network error")
            return pd.DataFrame({"ok": [True]})

        # Mock sleep to avoid real delays
        monkeypatch.setattr(time, "sleep", lambda x: None)

        result = provider.fetch_with_retry(
            flaky_func,
            label="test_flaky",
            max_retries=3,
            interval=0.01,
        )

        assert isinstance(result, pd.DataFrame)
        assert call_count["n"] == 3

    def test_fetch_with_retry_non_transient_error(self) -> None:
        """测试非瞬态错误直接抛出。"""
        provider = _FakeProvider()

        def bad_func(**kwargs):
            raise ValueError("logic error")

        with pytest.raises(DataFetchError):
            provider.fetch_with_retry(bad_func, label="test_bad")

    def test_validate_truncation_warning(self, caplog) -> None:
        """测试静默截断验证发出警告。"""
        provider = _FakeProvider()

        # 创建接近阈值的 DataFrame
        df = pd.DataFrame({"col": range(4500)})

        with caplog.at_level("WARNING"):
            provider.validate_truncation(
                df,
                source="tushare",
                data_type="moneyflow",
                trade_date="20240101",
            )

        # 应该有警告日志
        assert len(caplog.records) >= 1
        assert "truncation" in caplog.records[0].message.lower()

    def test_validate_truncation_no_warning(self, caplog) -> None:
        """测试数据量正常时无警告。"""
        provider = _FakeProvider()

        df = pd.DataFrame({"col": range(100)})

        with caplog.at_level("WARNING"):
            provider.validate_truncation(
                df,
                source="tushare",
                data_type="moneyflow",
                trade_date="20240101",
            )

        # 无警告
        assert len(caplog.records) == 0


class TestProviderRegistry:
    """ProviderRegistry 测试。"""

    def test_register_provider(self) -> None:
        """测试注册 Provider。"""
        registry = ProviderRegistry()
        provider = _FakeProvider()

        registry.register(provider)

        assert registry.get("fake") is provider
        assert "fake" in registry.list_all()

    def test_get_for_type(self) -> None:
        """测试按数据类型获取 Provider。"""
        registry = ProviderRegistry()
        provider = _FakeProvider()

        registry.register(provider)

        providers = registry.get_for_type("moneyflow")
        assert len(providers) == 1
        assert providers[0] is provider

    def test_get_for_type_unknown(self) -> None:
        """测试未知数据类型返回空列表。"""
        registry = ProviderRegistry()

        providers = registry.get_for_type("unknown_type")
        assert providers == []

    def test_list_types(self) -> None:
        """测试列出所有数据类型。"""
        registry = ProviderRegistry()
        provider = _FakeProvider()

        registry.register(provider)

        types = registry.list_types()
        assert "moneyflow" in types
        assert "limit_board" in types
