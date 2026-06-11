"""打板数据模块。

Tushare 接口：limit_list_d
所需积分：≥5000（8000 无限制）
文档：https://tushare.pro/document/2?doc_id=346

功能：
- 涨停/跌停列表
- 炸板数据
- 封单金额
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def fetch_limit_list(
    api: Any,
    *,
    trade_date: str | None = None,
    ts_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit_type: str | None = None,  # 'U' 涨停, 'D' 跌停
) -> pd.DataFrame:
    """获取涨跌停列表。

    Args:
        api: Tushare API 客户端
        trade_date: 交易日期（YYYYMMDD）
        ts_code: 股票代码
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）
        limit_type: 涨跌停类型（'U' 涨停, 'D' 跌停）

    Returns:
        DataFrame，字段包括：
        - ts_code: 股票代码
        - trade_date: 交易日期
        - up_stat: 涨跌停状态（U 涨停/D 跌停）
        - fd_amount: 封单金额（元）
        - close: 收盘价
        - pct_chg: 涨跌幅（%）
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

    df = api.limit_list_d(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    # 按涨跌停类型过滤
    if limit_type and "up_stat" in df.columns:
        df = df[df["up_stat"] == limit_type]

    return df


def get_limit_up_list(df: pd.DataFrame) -> pd.DataFrame:
    """提取涨停列表。

    Args:
        df: 打板 DataFrame

    Returns:
        涨停 DataFrame
    """
    if df.empty or "up_stat" not in df.columns:
        return pd.DataFrame()
    return df[df["up_stat"].str.startswith("U", na=False)]


def get_limit_down_list(df: pd.DataFrame) -> pd.DataFrame:
    """提取跌停列表。

    Args:
        df: 打板 DataFrame

    Returns:
        跌停 DataFrame
    """
    if df.empty or "up_stat" not in df.columns:
        return pd.DataFrame()
    return df[df["up_stat"].str.startswith("D", na=False)]


def get_broken_board(df: pd.DataFrame) -> pd.DataFrame:
    """提取炸板数据。

    炸板：当日曾涨停但最终未封住（up_stat 包含 '炸' 或类似标记）

    Args:
        df: 打板 DataFrame

    Returns:
        炸板 DataFrame
    """
    if df.empty or "up_stat" not in df.columns:
        return pd.DataFrame()
    # 炸板通常用特定标记，如 '炸' 或 'B'
    return df[df["up_stat"].str.contains("炸|B", na=False, regex=True)]


def get_strongest_sealers(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """获取封单金额最大的涨停股。

    Args:
        df: 打板 DataFrame
        top_n: 返回前 N 名

    Returns:
        封单最强的涨停 DataFrame
    """
    limit_up = get_limit_up_list(df)
    if limit_up.empty or "fd_amount" not in limit_up.columns:
        return pd.DataFrame()

    return limit_up.sort_values("fd_amount", ascending=False).head(top_n)
