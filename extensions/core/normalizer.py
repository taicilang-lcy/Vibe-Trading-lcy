"""数据规范化器。

统一单位、复权、字段名。根据 docs/data-source-integration-plan.md 第 4 节：
- Tushare 成交量单位是手（×100 → 股）
- Tushare 成交额单位是千元（×1000 → 元）
- Tushare 市值单位是万元（÷10000 → 亿元）
- Tushare 资金流单位是万元（×10000 → 元）

规范化执行清单：
1. 字段名统一（ts_code → stock_code 等）
2. 单位换算
3. 复权处理（可选）
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# 单位换算配置
# -------------------------------------------------------------------------

# Tushare 单位换算规则（来源：实测 + 官方文档交叉验证）
TUSHARE_UNIT_CONVERSIONS = {
    # 成交量：手 → 股
    "vol": {"multiplier": 100, "target_unit": "shares"},
    # 成交额：千元 → 元
    "amount": {"multiplier": 1000, "target_unit": "cny"},
    # 总市值：万元 → 亿元
    "total_mv": {"multiplier": 1e-4, "target_unit": "yi_cny"},
    # 流通市值：万元 → 亿元
    "circ_mv": {"multiplier": 1e-4, "target_unit": "yi_cny"},
    # 资金流向金额字段：万元 → 元
    "net_mf_amount": {"multiplier": 10000, "target_unit": "cny"},
    "buy_elg_amount": {"multiplier": 10000, "target_unit": "cny"},
    "buy_lg_amount": {"multiplier": 10000, "target_unit": "cny"},
    "buy_md_amount": {"multiplier": 10000, "target_unit": "cny"},
    "buy_sm_amount": {"multiplier": 10000, "target_unit": "cny"},
    "sell_elg_amount": {"multiplier": 10000, "target_unit": "cny"},
    "sell_lg_amount": {"multiplier": 10000, "target_unit": "cny"},
    "sell_md_amount": {"multiplier": 10000, "target_unit": "cny"},
    "sell_sm_amount": {"multiplier": 10000, "target_unit": "cny"},
}

# 字段别名映射（统一字段名）
FIELD_ALIASES = {
    "tushare": {
        "ts_code": "stock_code",
        "vol": "volume",
        "trade_date": "date",
    },
    "astockdata": {
        "code": "stock_code",
    },
}

# 目标单位配置（可配置）
NORMALIZATION_CONFIG = {
    "volume_unit": "shares",      # 成交量目标单位：股
    "amount_unit": "cny",         # 成交额目标单位：元
    "market_cap_unit": "yi_cny",  # 市值目标单位：亿元
    "flow_unit": "cny",           # 资金流目标单位：元
}


# -------------------------------------------------------------------------
# 核心函数
# -------------------------------------------------------------------------

def normalize(
    df: pd.DataFrame,
    source: str,
    *,
    adj_factor_df: pd.DataFrame | None = None,
    apply_qfq: bool = False,
    field_aliases: dict[str, str] | None = None,
) -> pd.DataFrame:
    """规范化 DataFrame：单位换算 → 字段名统一 → 复权处理（可选）。

    注意：单位换算必须在字段别名之前执行，因为换算规则基于原始字段名。

    Args:
        df: 原始 DataFrame
        source: 数据源名称（如 'tushare', 'astockdata'）
        adj_factor_df: 复权因子 DataFrame（可选）
        apply_qfq: 是否应用前复权（默认 False）
        field_aliases: 自定义字段别名（可选）

    Returns:
        规范化后的 DataFrame
    """
    if df is None or df.empty:
        return df

    result = df.copy()

    # Step 1: 单位换算（必须先于字段别名，因为换算规则基于原始字段名）
    result = apply_unit_conversions(result, source)

    # Step 2: 字段名统一
    aliases = FIELD_ALIASES.get(source, {})
    if field_aliases:
        aliases = {**aliases, **field_aliases}
    result = apply_field_aliases(result, aliases)

    # Step 3: 复权处理（可选）
    if apply_qfq and adj_factor_df is not None and not adj_factor_df.empty:
        result = apply_qfq_adjustment(result, adj_factor_df)

    return result


def apply_field_aliases(df: pd.DataFrame, aliases: dict[str, str]) -> pd.DataFrame:
    """应用字段别名映射。

    Args:
        df: DataFrame
        aliases: 字段别名字典 {旧名: 新名}

    Returns:
        重命名后的 DataFrame
    """
    existing_aliases = {k: v for k, v in aliases.items() if k in df.columns}
    if existing_aliases:
        df = df.rename(columns=existing_aliases)
        logger.debug("Applied field aliases: %s", existing_aliases)
    return df


def apply_unit_conversions(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """应用单位换算。

    Args:
        df: DataFrame
        source: 数据源名称

    Returns:
        单位换算后的 DataFrame
    """
    conversions = {}
    if source == "tushare":
        conversions = TUSHARE_UNIT_CONVERSIONS

    for field, config in conversions.items():
        if field in df.columns:
            multiplier = config["multiplier"]
            df[field] = df[field] * multiplier
            logger.debug(
                "Converted %s: multiplier=%s → target_unit=%s",
                field, multiplier, config["target_unit"]
            )

    return df


def apply_qfq_adjustment(
    df: pd.DataFrame,
    adj_factor_df: pd.DataFrame,
    *,
    price_columns: list[str] = ["open", "high", "low", "close"],
) -> pd.DataFrame:
    """应用前复权调整。

    参考 docs/data-source-integration-plan.md 第 4.2 节：
    Tushare pro_bar(adj='qfq') 以 end_date 为基准，非最新交易日，导致与行情软件不一致。
    推荐方式：daily + adj_factor 自行计算，以最新 adj_factor 为基准。

    计算公式：
    close_qfq = close × adj_factor / latest_adj_factor

    Args:
        df: 价格 DataFrame（需包含 stock_code 或 ts_code）
        adj_factor_df: 复权因子 DataFrame（需包含 stock_code, date, adj_factor）
        price_columns: 需复权的价格列

    Returns:
        复权后的 DataFrame
    """
    if "stock_code" not in df.columns:
        logger.warning("Cannot apply QFQ: missing stock_code column")
        return df

    # 确保 adj_factor_df 有正确的字段
    if "stock_code" not in adj_factor_df.columns and "ts_code" in adj_factor_df.columns:
        adj_factor_df = adj_factor_df.rename(columns={"ts_code": "stock_code"})
    if "date" not in adj_factor_df.columns and "trade_date" in adj_factor_df.columns:
        adj_factor_df = adj_factor_df.rename(columns={"trade_date": "date"})

    result = df.copy()

    for stock_code in df["stock_code"].unique():
        stock_df = df[df["stock_code"] == stock_code]
        stock_adj = adj_factor_df[adj_factor_df["stock_code"] == stock_code]

        if stock_adj.empty:
            continue

        # 以最新的 adj_factor 为基准
        stock_adj = stock_adj.sort_values("date", ascending=False)
        latest_adj = stock_adj["adj_factor"].iloc[0]

        # 合并 adj_factor
        merged = stock_df.merge(
            stock_adj[["date", "adj_factor"]],
            on="date",
            how="left"
        )

        # ffill 缺失的复权因子
        merged["adj_factor"] = merged["adj_factor"].ffill()

        # 计算前复权价格
        for col in price_columns:
            if col in merged.columns:
                merged[f"{col}_qfq"] = merged[col] * merged["adj_factor"] / latest_adj

        # 更新 result
        result.loc[result["stock_code"] == stock_code, :] = merged.drop(columns="adj_factor")

    return result


# -------------------------------------------------------------------------
# 辅助函数
# -------------------------------------------------------------------------

def convert_tushare_volume_to_shares(vol: pd.Series | float) -> pd.Series | float:
    """将 Tushare 成交量从手转换为股。

    Args:
        vol: 成交量（手）

    Returns:
        成交量（股）
    """
    return vol * 100


def convert_tushare_amount_to_cny(amount: pd.Series | float) -> pd.Series | float:
    """将 Tushare 成交额从千元转换为元。

    Args:
        amount: 成交额（千元）

    Returns:
        成交额（元）
    """
    return amount * 1000


def convert_tushare_mv_to_yi(mv: pd.Series | float) -> pd.Series | float:
    """将 Tushare 市值从万元转换为亿元。

    Args:
        mv: 市值（万元）

    Returns:
        市值（亿元）
    """
    return mv * 1e-4


def convert_tushare_flow_to_cny(flow: pd.Series | float) -> pd.Series | float:
    """将 Tushare 资金流从万元转换为元。

    Args:
        flow: 资金流（万元）

    Returns:
        资金流（元）
    """
    return flow * 10000


def parse_tushare_date(date_str: str | pd.Series) -> pd.Timestamp | pd.Series:
    """解析 Tushare YYYYMMDD 格式日期。

    Args:
        date_str: 日期字符串或 Series

    Returns:
        Timestamp 或 Series
    """
    if isinstance(date_str, str):
        if len(date_str) == 8 and date_str.isdigit():
            return pd.to_datetime(date_str, format="%Y%m%d")
        return pd.to_datetime(date_str)
    return pd.to_datetime(date_str, format="%Y%m%d", errors="coerce")