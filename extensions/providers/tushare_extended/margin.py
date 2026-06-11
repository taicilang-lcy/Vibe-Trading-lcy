"""融资融券模块。

Tushare 接口：margin, margin_detail
所需积分：≥2000
文档：https://tushare.pro/document/2?doc_id=58

单位说明：
- rzye（融资余额）：元
- rqye（融券余额）：元
- rqyl（融券余量）：股
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def fetch_margin(
    api: Any,
    *,
    trade_date: str | None = None,
    ts_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """获取融资融券数据。

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
        - rzye: 融资余额（元）
        - rqmre: 融资买入额（元）
        - rzche: 融资偿还额（元）
        - rqye: 融券余额（元）
        - rqmcl: 融券卖出量（股）
        - rqchl: 融券偿还量（股）
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

    df = api.margin(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    return df


def fetch_margin_detail(
    api: Any,
    *,
    trade_date: str | None = None,
    ts_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """获取融资融券明细。

    Args:
        api: Tushare API 客户端
        trade_date: 交易日期（YYYYMMDD）
        ts_code: 股票代码
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）

    Returns:
        明细 DataFrame
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

    df = api.margin_detail(**params)
    return df if df is not None else pd.DataFrame()


def get_top_margin_stocks(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """获取融资余额最高的股票。

    Args:
        df: 融资融券 DataFrame
        top_n: 返回前 N 名

    Returns:
        融资余额排名 DataFrame
    """
    if df.empty or "rzye" not in df.columns:
        return pd.DataFrame()

    return df.sort_values("rzye", ascending=False).head(top_n)


def calculate_margin_change(df: pd.DataFrame) -> pd.DataFrame:
    """计算融资融券变化。

    Args:
        df: 融资融券 DataFrame（需按日期排序）

    Returns:
        带变化字段的 DataFrame
    """
    if df.empty:
        return df

    result = df.copy()

    if "rzye" in result.columns:
        result["rzye_change"] = result["rzye"].diff()
        result["rzye_change_pct"] = result["rzye"].pct_change() * 100

    if "rqye" in result.columns:
        result["rqye_change"] = result["rqye"].diff()
        result["rqye_change_pct"] = result["rqye"].pct_change() * 100

    return result
