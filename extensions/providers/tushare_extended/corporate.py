"""复权因子/分红/预告模块。

Tushare 接口：adj_factor, dividend, forecast, express
文档：
- adj_factor: https://tushare.pro/document/2?doc_id=146
- dividend: https://tushare.pro/document/2?doc_id=103
- forecast: https://tushare.pro/document/2?doc_id=54
- express: https://tushare.pro/document/2?doc_id=55

重点：adj_factor 用于计算前复权价格。
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def fetch_adj_factor(
    api: Any,
    *,
    ts_code: str | None = None,
    trade_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """获取复权因子数据。

    建议：按 trade_date 拉全市场更高效（~220 次/年），不按 ts_code（~5000 次/股票）。

    Args:
        api: Tushare API 客户端
        ts_code: 股票代码
        trade_date: 交易日期（YYYYMMDD）
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）

    Returns:
        DataFrame，字段包括：
        - ts_code: 股票代码
        - trade_date: 交易日期
        - adj_factor: 复权因子
    """
    params: dict[str, Any] = {}
    if ts_code:
        params["ts_code"] = ts_code
    if trade_date:
        params["trade_date"] = trade_date
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    df = api.adj_factor(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    return df


def apply_qfq(
    price_df: pd.DataFrame,
    adj_df: pd.DataFrame,
    *,
    price_date_col: str = "trade_date",
    price_code_col: str = "ts_code",
) -> pd.DataFrame:
    """应用前复权调整。

    参考 docs/data-source-integration-plan.md 第 4.2 节：
    以最新的 adj_factor 为基准计算前复权价格。

    公式：close_qfq = close × adj_factor / latest_adj_factor

    Args:
        price_df: 价格 DataFrame（需包含 open, high, low, close）
        adj_df: 复权因子 DataFrame
        price_date_col: 价格 DataFrame 的日期列名
        price_code_col: 价格 DataFrame 的代码列名

    Returns:
        带前复权价格的 DataFrame
    """
    if price_df.empty or adj_df.empty:
        return price_df

    result = price_df.copy()

    # 确保日期格式一致
    if "trade_date" in adj_df.columns:
        adj_df = adj_df.rename(columns={"trade_date": price_date_col})

    # 按 ts_code 分别处理
    if price_code_col in result.columns and "ts_code" in adj_df.columns:
        for code in result[price_code_col].unique():
            stock_price = result[result[price_code_col] == code].copy()
            stock_adj = adj_df[adj_df["ts_code"] == code].copy()

            if stock_adj.empty:
                continue

            # 以最新的 adj_factor 为基准
            stock_adj = stock_adj.sort_values(price_date_col, ascending=False)
            latest_adj = stock_adj["adj_factor"].iloc[0]

            # 合并 adj_factor
            merged = stock_price.merge(
                stock_adj[[price_date_col, "adj_factor"]],
                on=price_date_col,
                how="left"
            )

            # ffill 缺失的复权因子
            merged["adj_factor"] = merged["adj_factor"].ffill()

            # 计算前复权价格
            for col in ["open", "high", "low", "close"]:
                if col in merged.columns:
                    merged[f"{col}_qfq"] = merged[col] * merged["adj_factor"] / latest_adj

            # 更新 result
            merged = merged.drop(columns=["adj_factor"], errors="ignore")
            result.loc[result[price_code_col] == code] = merged

    return result


def fetch_dividend(
    api: Any,
    *,
    ts_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """获取分红送转数据。

    Args:
        api: Tushare API 客户端
        ts_code: 股票代码
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）

    Returns:
        DataFrame，字段包括：
        - ts_code: 股票代码
        - end_date: 分红年度
        - div_proc: 实施进度
        - stk_div: 每股送股
        - cash_div: 每股派息
        - ex_date: 除权除息日
    """
    params: dict[str, Any] = {}
    if ts_code:
        params["ts_code"] = ts_code
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    df = api.dividend(**params)
    return df if df is not None else pd.DataFrame()


def fetch_forecast(
    api: Any,
    *,
    ts_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """获取业绩预告数据。

    Args:
        api: Tushare API 客户端
        ts_code: 股票代码
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）

    Returns:
        DataFrame，字段包括：
        - ts_code: 股票代码
        - ann_date: 公告日期
        - end_date: 报告期
        - type: 业绩预告类型
        - p_change_min: 预告净利润变动幅度下限（%）
        - p_change_max: 预告净利润变动幅度上限（%）
    """
    params: dict[str, Any] = {}
    if ts_code:
        params["ts_code"] = ts_code
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    df = api.forecast(**params)
    return df if df is not None else pd.DataFrame()


def fetch_express(
    api: Any,
    *,
    ts_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """获取业绩快报数据。

    Args:
        api: Tushare API 客户端
        ts_code: 股票代码
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）

    Returns:
        DataFrame，字段包括：
        - ts_code: 股票代码
        - ann_date: 公告日期
        - end_date: 报告期
        - revenue: 营业收入
        - operate_profit: 营业利润
        - n_income: 净利润
    """
    params: dict[str, Any] = {}
    if ts_code:
        params["ts_code"] = ts_code
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    df = api.express(**params)
    return df if df is not None else pd.DataFrame()
