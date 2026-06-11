"""资金流向模块。

Tushare 接口：moneyflow
所需积分：≥2000
文档：https://tushare.pro/document/2?doc_id=342

单位说明：
- 所有金额字段单位为**万元**
- Normalizer 会将其转换为**元**
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from extensions.core.normalizer import convert_tushare_flow_to_cny


def fetch_moneyflow(
    api: Any,
    *,
    ts_code: str | None = None,
    trade_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """获取个股资金流向。

    Args:
        api: Tushare API 客户端
        ts_code: 股票代码（如 000001.SZ）
        trade_date: 交易日期（YYYYMMDD）
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）

    Returns:
        DataFrame，字段包括：
        - ts_code: 股票代码
        - trade_date: 交易日期
        - net_mf_amount: 净流入金额（万元 → 元）
        - buy_elg_amount: 超大单买入（万元 → 元）
        - buy_lg_amount: 大单买入（万元 → 元）
        - buy_md_amount: 中单买入（万元 → 元）
        - buy_sm_amount: 小单买入（万元 → 元）
        - sell_elg_amount: 超大单卖出（万元 → 元）
        - sell_lg_amount: 大单卖出（万元 → 元）
        - sell_md_amount: 中单卖出（万元 → 元）
        - sell_sm_amount: 小单卖出（万元 → 元）
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

    df = api.moneyflow(**params)

    if df is None or df.empty:
        return pd.DataFrame()

    # 单位换算：万元 → 元
    amount_fields = [
        "net_mf_amount",
        "buy_elg_amount", "buy_lg_amount", "buy_md_amount", "buy_sm_amount",
        "sell_elg_amount", "sell_lg_amount", "sell_md_amount", "sell_sm_amount",
    ]
    for field in amount_fields:
        if field in df.columns:
            df[field] = convert_tushare_flow_to_cny(df[field])

    return df


def get_net_inflow_ranking(
    df: pd.DataFrame,
    top_n: int = 10,
    by: str = "net_mf_amount",
) -> pd.DataFrame:
    """获取资金净流入排名。

    Args:
        df: 资金流向 DataFrame
        top_n: 返回前 N 名
        by: 排序字段（默认 net_mf_amount）

    Returns:
        排名 DataFrame
    """
    if df.empty or by not in df.columns:
        return pd.DataFrame()

    return df.sort_values(by, ascending=False).head(top_n)


def get_sector_moneyflow(
    df: pd.DataFrame,
    sector_map: dict[str, str],
) -> pd.DataFrame:
    """按板块汇总资金流向。

    Args:
        df: 资金流向 DataFrame
        sector_map: {ts_code: sector_name} 映射

    Returns:
        板块资金流向汇总
    """
    if df.empty or "ts_code" not in df.columns:
        return pd.DataFrame()

    df["sector"] = df["ts_code"].map(sector_map)
    return df.groupby("sector").agg({
        "net_mf_amount": "sum",
        "buy_elg_amount": "sum",
        "sell_elg_amount": "sum",
    }).reset_index()
