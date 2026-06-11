"""大宗交易模块。

Tushare 接口：block_trade
所需积分：≥2000
文档：https://tushare.pro/document/2?doc_id=47

单位说明：
- trade_amount: 成交金额（元）
- trade_price: 成交价格（元）
- trade_vol: 成交量（股）
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def fetch_block_trade(
    api: Any,
    *,
    trade_date: str | None = None,
    ts_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """获取大宗交易数据。

    Args:
        api: Tushare API 客户端
        trade_date: 交易日期（YYYYMMDD）
        ts_code: 股票代码
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）

    Returns:
        DataFrame，字段包括：
        - ts_code: 股票代码
        - trade_date: 交易日期
        - trade_price: 成交价
        - trade_vol: 成交量（股）
        - trade_amount: 成交金额（元）
        - buyer_name: 买方营业部
        - seller_name: 卖方营业部
        - premium_rate: 溢价率（%）
    """
    params: dict[str, Any] = {}
    if trade_date:
        params["trade_date"] = trade_date
    if ts_code:
        params["ts_code"] = ts_code
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    df = api.block_trade(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    # 计算溢价率（如果有收盘价字段）
    # premium_rate = (trade_price - close) / close * 100

    return df


def get_premium_trades(df: pd.DataFrame, min_premium: float = 5.0) -> pd.DataFrame:
    """获取溢价大宗交易。

    Args:
        df: 大宗交易 DataFrame
        min_premium: 最小溢价率（%）

    Returns:
        溢价交易 DataFrame
    """
    if df.empty:
        return pd.DataFrame()

    if "premium_rate" in df.columns:
        return df[df["premium_rate"] >= min_premium]

    return pd.DataFrame()


def get_discount_trades(df: pd.DataFrame, max_discount: float = -5.0) -> pd.DataFrame:
    """获取折价大宗交易。

    Args:
        df: 大宗交易 DataFrame
        max_discount: 最大折价率（%），负数表示折价

    Returns:
        折价交易 DataFrame
    """
    if df.empty:
        return pd.DataFrame()

    if "premium_rate" in df.columns:
        return df[df["premium_rate"] <= max_discount]

    return pd.DataFrame()


def get_top_block_trades(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """获取成交金额最大的大宗交易。

    Args:
        df: 大宗交易 DataFrame
        top_n: 返回前 N 名

    Returns:
        成交金额排名 DataFrame
    """
    if df.empty or "trade_amount" not in df.columns:
        return pd.DataFrame()

    return df.sort_values("trade_amount", ascending=False).head(top_n)


def get_frequent_block_stocks(df: pd.DataFrame, min_count: int = 3) -> pd.DataFrame:
    """获取频繁大宗交易的股票。

    Args:
        df: 大宗交易 DataFrame
        min_count: 最小交易次数

    Returns:
        频繁交易股票 DataFrame
    """
    if df.empty or "ts_code" not in df.columns:
        return pd.DataFrame()

    summary = df.groupby("ts_code").agg({
        "trade_amount": "sum",
        "trade_vol": "sum",
        "trade_date": "count",  # 交易次数
    }).reset_index()

    summary.columns = ["ts_code", "total_amount", "total_vol", "trade_count"]
    return summary[summary["trade_count"] >= min_count].sort_values(
        "trade_count", ascending=False
    )
