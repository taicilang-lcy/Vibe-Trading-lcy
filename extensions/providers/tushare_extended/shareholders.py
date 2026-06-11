"""股东户数模块。

Tushare 接口：stk_holdernumber
所需积分：≥2000
文档：https://tushare.pro/document/2?doc_id=329

注意：此接口更新频率为季度，需按 ts_code 拉取。
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def fetch_shareholders(
    api: Any,
    *,
    ts_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """获取股东户数数据。

    Args:
        api: Tushare API 客户端
        ts_code: 股票代码（必须）
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）

    Returns:
        DataFrame，字段包括：
        - ts_code: 股票代码
        - ann_date: 公告日期
        - end_date: 截止日期
        - holder_num: 股东户数
        - holder_num_change: 股东户数变化
    """
    params: dict[str, Any] = {}
    if ts_code:
        params["ts_code"] = ts_code
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    df = api.stk_holdernumber(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    return df


def fetch_batch_shareholders(
    api: Any,
    codes: list[str],
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """批量获取多只股票的股东户数。

    Args:
        api: Tushare API 客户端
        codes: 股票代码列表
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）

    Returns:
        合并后的 DataFrame
    """
    frames: list[pd.DataFrame] = []

    for code in codes:
        try:
            df = fetch_shareholders(api, ts_code=code, start_date=start_date, end_date=end_date)
            if df is not None and not df.empty:
                frames.append(df)
        except Exception:
            continue

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def calculate_holder_change(df: pd.DataFrame) -> pd.DataFrame:
    """计算股东户数变化。

    Args:
        df: 股东户数 DataFrame

    Returns:
        带变化字段的 DataFrame
    """
    if df.empty or "holder_num" not in df.columns:
        return df

    result = df.copy()
    result = result.sort_values(["ts_code", "end_date"])
    result["holder_change"] = result.groupby("ts_code")["holder_num"].diff()
    result["holder_change_pct"] = result.groupby("ts_code")["holder_num"].pct_change() * 100

    return result


def get_decreasing_holders(df: pd.DataFrame, min_decrease_pct: float = 10.0) -> pd.DataFrame:
    """获取股东户数下降的股票。

    股东户数下降通常意味着筹码集中，可能是利好信号。

    Args:
        df: 股东户数 DataFrame（需已计算 holder_change_pct）
        min_decrease_pct: 最小下降幅度（%）

    Returns:
        股东户数下降的 DataFrame
    """
    if df.empty or "holder_change_pct" not in df.columns:
        return pd.DataFrame()

    return df[df["holder_change_pct"] <= -min_decrease_pct]


def get_increasing_holders(df: pd.DataFrame, min_increase_pct: float = 10.0) -> pd.DataFrame:
    """获取股东户数上升的股票。

    股东户数上升通常意味着筹码分散，可能是利空信号。

    Args:
        df: 股东户数 DataFrame（需已计算 holder_change_pct）
        min_increase_pct: 最小上升幅度（%）

    Returns:
        股东户数上升的 DataFrame
    """
    if df.empty or "holder_change_pct" not in df.columns:
        return pd.DataFrame()

    return df[df["holder_change_pct"] >= min_increase_pct]
