"""测试 Tushare Extended Provider。"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from extensions.providers.tushare_extended.provider import (
    TushareExtendedProvider,
    TUSHARE_TOKEN_PLACEHOLDERS,
)


class TestTushareExtendedProvider:
    """TushareExtendedProvider 测试。"""

    def test_provider_properties(self) -> None:
        """测试 Provider 属性。"""
        provider = TushareExtendedProvider()

        assert provider.name == "tushare_extended"
        assert "资金" in provider.description or "Tushare" in provider.description
        assert "moneyflow" in provider.supported_types
        assert "limit_board" in provider.supported_types

    def test_is_available_with_token(self, monkeypatch) -> None:
        """测试有 token 时可用。"""
        monkeypatch.setenv("TUSHARE_TOKEN", "test_token_12345")

        provider = TushareExtendedProvider()
        assert provider.is_available()

    def test_is_available_without_token(self, monkeypatch) -> None:
        """测试无 token 时不可用。"""
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

        provider = TushareExtendedProvider()
        assert not provider.is_available()

    def test_is_available_with_placeholder(self, monkeypatch) -> None:
        """测试 token 占位符时不可用。"""
        monkeypatch.setenv("TUSHARE_TOKEN", "your-tushare-token")

        provider = TushareExtendedProvider()
        assert not provider.is_available()

    def test_fetch_unsupported_type(self, monkeypatch) -> None:
        """测试获取不支持的数据类型。"""
        monkeypatch.setenv("TUSHARE_TOKEN", "test_token")

        provider = TushareExtendedProvider()

        with pytest.raises(Exception):  # DataFetchError
            provider.fetch("unsupported_type")


class TestMoneyflowFetch:
    """资金流向获取测试。"""

    def test_fetch_moneyflow_by_trade_date(self, monkeypatch) -> None:
        """测试按交易日期获取资金流向。"""
        monkeypatch.setenv("TUSHARE_TOKEN", "test_token")

        mock_api = MagicMock()
        mock_api.moneyflow.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ", "600519.SH"],
            "trade_date": ["20240101", "20240101"],
            "net_mf_amount": [100, 200],  # 万元
        })

        provider = TushareExtendedProvider()
        provider._api = mock_api

        df = provider._fetch_moneyflow(mock_api, trade_date="20240101")

        assert len(df) == 2
        mock_api.moneyflow.assert_called_once()

    def test_fetch_moneyflow_by_codes(self, monkeypatch) -> None:
        """测试按股票代码获取资金流向。"""
        monkeypatch.setenv("TUSHARE_TOKEN", "test_token")

        mock_api = MagicMock()
        mock_api.moneyflow.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20240101"],
            "net_mf_amount": [100],
        })

        provider = TushareExtendedProvider()
        provider._api = mock_api

        df = provider._fetch_moneyflow(
            mock_api,
            codes=["000001.SZ"],
            start_date="20240101",
            end_date="20240131",
        )

        assert len(df) == 1


class TestLimitBoardFetch:
    """打板数据获取测试。"""

    def test_fetch_limit_list(self, monkeypatch) -> None:
        """测试获取打板数据。"""
        monkeypatch.setenv("TUSHARE_TOKEN", "test_token")

        mock_api = MagicMock()
        mock_api.limit_list_d.return_value = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20240101"],
            "up_stat": ["U"],
            "fd_amount": [1000000],
        })

        provider = TushareExtendedProvider()
        provider._api = mock_api

        df = provider._fetch_limit_board(mock_api, trade_date="20240101")

        assert len(df) == 1
        mock_api.limit_list_d.assert_called_once()


class TestRateLimiting:
    """限流测试。"""

    def test_rate_limit_interval(self, monkeypatch) -> None:
        """测试限流间隔。"""
        monkeypatch.setenv("TUSHARE_TOKEN", "test_token")

        provider = TushareExtendedProvider()
        provider._rate_limit_interval = 0.1  # 加速测试

        mock_api = MagicMock()
        mock_api.moneyflow.return_value = pd.DataFrame({"col": [1]})

        # 记录调用时间
        start = time.monotonic()
        provider._call_api_with_retry(
            mock_api.moneyflow,
            label="test",
        )
        elapsed = time.monotonic() - start

        # 应该至少等待 rate_limit_interval
        assert elapsed >= 0.1


class TestRetryMechanism:
    """重试机制测试。"""

    def test_retry_on_transient_error(self, monkeypatch) -> None:
        """测试瞬态错误重试。"""
        monkeypatch.setenv("TUSHARE_TOKEN", "test_token")

        # Mock sleep 避免真实延迟
        monkeypatch.setattr(time, "sleep", lambda x: None)

        mock_api = MagicMock()
        call_count = {"n": 0}

        def flaky_moneyflow(**kwargs):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise ConnectionError("network error")
            return pd.DataFrame({"col": [1]})

        mock_api.moneyflow = flaky_moneyflow

        provider = TushareExtendedProvider()
        provider._api = mock_api

        df = provider._call_api_with_retry(
            mock_api.moneyflow,
            label="test_retry",
        )

        assert len(df) == 1
        assert call_count["n"] == 3

    def test_retry_exhausted(self, monkeypatch) -> None:
        """测试重试耗尽抛出异常。"""
        monkeypatch.setenv("TUSHARE_TOKEN", "test_token")
        monkeypatch.setattr(time, "sleep", lambda x: None)

        mock_api = MagicMock()
        mock_api.moneyflow.side_effect = ConnectionError("always fails")

        provider = TushareExtendedProvider()
        provider._api = mock_api

        with pytest.raises(TimeoutError):
            provider._call_api_with_retry(
                mock_api.moneyflow,
                label="test_fail",
                max_retries=2,
            )


class TestTruncationValidation:
    """静默截断验证测试。"""

    def test_truncation_warning_high_row_count(self, caplog) -> None:
        """测试高行数时的截断警告。"""
        provider = TushareExtendedProvider()

        # 创建接近阈值的 DataFrame
        df = pd.DataFrame({"col": range(4900)})

        with caplog.at_level("WARNING"):
            provider.validate_truncation(
                df,
                source="tushare",
                data_type="moneyflow",
                trade_date="20240101",
            )

        assert len(caplog.records) >= 1
        assert "truncation" in caplog.records[0].message.lower()

    def test_no_warning_normal_rows(self, caplog) -> None:
        """测试正常行数无警告。"""
        provider = TushareExtendedProvider()

        df = pd.DataFrame({"col": range(100)})

        with caplog.at_level("WARNING"):
            provider.validate_truncation(
                df,
                source="tushare",
                data_type="moneyflow",
                trade_date="20240101",
            )

        assert len(caplog.records) == 0
