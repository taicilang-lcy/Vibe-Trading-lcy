"""测试 normalizer 模块。"""

from __future__ import annotations

import pandas as pd
import pytest

from extensions.core.normalizer import (
    normalize,
    apply_field_aliases,
    apply_unit_conversions,
    convert_tushare_volume_to_shares,
    convert_tushare_amount_to_cny,
    convert_tushare_mv_to_yi,
    convert_tushare_flow_to_cny,
    parse_tushare_date,
)


class TestFieldAliases:
    """字段别名测试。"""

    def test_apply_aliases_basic(self) -> None:
        """测试基本字段别名。"""
        df = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "vol": [100],
            "trade_date": ["20240101"],
        })

        result = apply_field_aliases(df, {"ts_code": "stock_code", "vol": "volume"})

        assert "stock_code" in result.columns
        assert "volume" in result.columns
        assert "ts_code" not in result.columns

    def test_apply_aliases_partial(self) -> None:
        """测试部分字段别名。"""
        df = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "other": [123],
        })

        result = apply_field_aliases(df, {"ts_code": "stock_code", "missing": "new_name"})

        assert "stock_code" in result.columns
        assert "other" in result.columns
        assert "missing" not in result.columns

    def test_apply_aliases_empty(self) -> None:
        """测试空别名映射。"""
        df = pd.DataFrame({"col": [1]})

        result = apply_field_aliases(df, {})

        pd.testing.assert_frame_equal(result, df)


class TestUnitConversions:
    """单位换算测试。"""

    def test_volume_conversion(self) -> None:
        """测试成交量换算（手 → 股）。"""
        df = pd.DataFrame({"vol": [100]})
        result = apply_unit_conversions(df, "tushare")

        # 100 手 → 100 * 100 = 10000 股
        assert result["vol"].iloc[0] == 100 * 100

    def test_amount_conversion(self) -> None:
        """测试成交额换算（千元 → 元）。"""
        df = pd.DataFrame({"amount": [1000]})
        result = apply_unit_conversions(df, "tushare")

        # 1000 千元 → 1000 * 1000 = 1,000,000 元
        assert result["amount"].iloc[0] == 1000 * 1000

    def test_market_cap_conversion(self) -> None:
        """测试市值换算（万元 → 亿元）。"""
        df = pd.DataFrame({"total_mv": [100000]})  # 10 亿元
        result = apply_unit_conversions(df, "tushare")

        # 100000 万元 → 10 亿元
        assert result["total_mv"].iloc[0] == 100000 * 1e-4

    def test_flow_conversion(self) -> None:
        """测试资金流换算（万元 → 元）。"""
        df = pd.DataFrame({"net_mf_amount": [100]})  # 100 万元
        result = apply_unit_conversions(df, "tushare")

        # 100 万元 → 100 * 10000 = 1,000,000 元
        assert result["net_mf_amount"].iloc[0] == 100 * 10000

    def test_unknown_source(self) -> None:
        """测试未知数据源不做换算。"""
        df = pd.DataFrame({"vol": [100]})
        result = apply_unit_conversions(df, "unknown_source")

        # 无变化
        assert result["vol"].iloc[0] == 100


class TestHelperFunctions:
    """辅助函数测试。"""

    def test_convert_volume_to_shares(self) -> None:
        """测试成交量换算函数。"""
        assert convert_tushare_volume_to_shares(100) == 100 * 100

        series = pd.Series([1, 2, 3])
        result = convert_tushare_volume_to_shares(series)
        pd.testing.assert_series_equal(result, series * 100)

    def test_convert_amount_to_cny(self) -> None:
        """测试成交额换算函数。"""
        assert convert_tushare_amount_to_cny(1000) == 1000 * 1000

    def test_convert_mv_to_yi(self) -> None:
        """测试市值换算函数。"""
        assert convert_tushare_mv_to_yi(100000) == 100000 * 1e-4

    def test_convert_flow_to_cny(self) -> None:
        """测试资金流换算函数。"""
        assert convert_tushare_flow_to_cny(100) == 100 * 10000

    def test_parse_tushare_date_string(self) -> None:
        """测试日期解析。"""
        result = parse_tushare_date("20240101")
        assert result == pd.Timestamp("2024-01-01")

        # 带 - 的日期
        result = parse_tushare_date("2024-01-01")
        assert result == pd.Timestamp("2024-01-01")

    def test_parse_tushare_date_series(self) -> None:
        """测试日期 Series 解析。"""
        series = pd.Series(["20240101", "20240102", "20240103"])
        result = parse_tushare_date(series)

        expected = pd.to_datetime(series, format="%Y%m%d")
        pd.testing.assert_series_equal(result, expected)


class TestNormalize:
    """normalize 主函数测试。"""

    def test_normalize_empty_dataframe(self) -> None:
        """测试空 DataFrame。"""
        df = pd.DataFrame()
        result = normalize(df, "tushare")

        pd.testing.assert_frame_equal(result, df)

    def test_normalize_none(self) -> None:
        """测试 None 输入。"""
        result = normalize(None, "tushare")

        assert result is None

    def test_normalize_full_pipeline(self) -> None:
        """测试完整规范化流程。"""
        df = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20240101"],
            "vol": [100],      # 手
            "amount": [1000],  # 千元
        })

        result = normalize(df, "tushare")

        # 字段重命名
        assert "stock_code" in result.columns
        assert "date" in result.columns

        # 单位换算
        assert result["volume"].iloc[0] == 100 * 100
        assert result["amount"].iloc[0] == 1000 * 1000

    def test_normalize_with_custom_aliases(self) -> None:
        """测试自定义别名。"""
        df = pd.DataFrame({"custom_col": [1]})

        result = normalize(df, "tushare", field_aliases={"custom_col": "new_col"})

        assert "new_col" in result.columns
