"""龙虎榜模块。

Tushare 接口：top_list, top_inst
所需积分：≥2000
文档：https://tushare.pro/document/2?doc_id=345

功能：
- 龙虎榜明细
- 机构动向
- 游资跟踪
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def fetch_dragon_tiger(
    api: Any,
    *,
    trade_date: str | None = None,
    ts_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    include_inst: bool = True,
) -> pd.DataFrame:
    """获取龙虎榜数据。

    Args:
        api: Tushare API 客户端
        trade_date: 交易日期（YYYYMMDD）
        ts_code: 股票代码
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）
        include_inst: 是否包含机构明细

    Returns:
        DataFrame，字段包括：
        - ts_code: 股票代码
        - trade_date: 交易日期
        - exalter: 营业部名称
        - buy_amount: 买入金额
        - sell_amount: 卖出金额
        - net_buy: 净买入金额
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

    # 获取龙虎榜列表
    df_list = api.top_list(**params)

    if df_list is None or df_list.empty:
        return pd.DataFrame()

    # 合并机构明细
    if include_inst:
        try:
            df_inst = api.top_inst(**params)
            if df_inst is not None and not df_inst.empty:
                df_list = pd.concat([df_list, df_inst], ignore_index=True)
        except Exception:
            pass

    return df_list


def get_hot_money_tracking(df: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """获取游资活跃度排名。

    Args:
        df: 龙虎榜 DataFrame
        top_n: 返回前 N 名

    Returns:
        游资活跃度 DataFrame
    """
    if df.empty or "exalter" not in df.columns:
        return pd.DataFrame()

    # 按营业部汇总
    summary = df.groupby("exalter").agg({
        "buy_amount": "sum",
        "sell_amount": "sum",
        "ts_code": "count",  # 出现次数
    }).reset_index()

    summary.columns = ["exalter", "total_buy", "total_sell", "appearance_count"]
    summary["net_buy"] = summary["total_buy"] - summary["total_sell"]

    return summary.sort_values("appearance_count", ascending=False).head(top_n)


def get_institution_activity(df: pd.DataFrame) -> pd.DataFrame:
    """提取机构动向。

    Args:
        df: 龙虎榜 DataFrame

    Returns:
        机构动向 DataFrame
    """
    if df.empty or "exalter" not in df.columns:
        return pd.DataFrame()

    # 机构通常在 exalter 字段中包含 "机构专用" 或 "机构"
    inst_df = df[df["exalter"].str.contains("机构", na=False)]
    return inst_df


def get_stock_dragon_tiger_summary(df: pd.DataFrame) -> pd.DataFrame:
    """按股票汇总龙虎榜数据。

    Args:
        df: 龙虎榜 DataFrame

    Returns:
        股票汇总 DataFrame
    """
    if df.empty or "ts_code" not in df.columns:
        return pd.DataFrame()

    return df.groupby("ts_code").agg({
        "buy_amount": "sum",
        "sell_amount": "sum",
        "exalter": "count",  # 营业部数量
    }).reset_index().rename(columns={"exalter": "broker_count"})
