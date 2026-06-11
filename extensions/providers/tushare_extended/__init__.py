"""Tushare 8000 积分扩展数据源。

提供以下接口：
- moneyflow: 个股资金流向
- limit_board: 打板数据
- dragon_tiger: 龙虎榜
- margin: 融资融券
- block_trade: 大宗交易
- shareholders: 股东户数
- adj_factor: 复权因子
"""

from extensions.providers.tushare_extended.provider import TushareExtendedProvider
from extensions.providers.tushare_extended.moneyflow import fetch_moneyflow
from extensions.providers.tushare_extended.limit_board import fetch_limit_list
from extensions.providers.tushare_extended.dragon_tiger import fetch_dragon_tiger
from extensions.providers.tushare_extended.margin import fetch_margin
from extensions.providers.tushare_extended.block_trade import fetch_block_trade
from extensions.providers.tushare_extended.shareholders import fetch_shareholders
from extensions.providers.tushare_extended.corporate import fetch_adj_factor

__all__ = [
    "TushareExtendedProvider",
    "fetch_moneyflow",
    "fetch_limit_list",
    "fetch_dragon_tiger",
    "fetch_margin",
    "fetch_block_trade",
    "fetch_shareholders",
    "fetch_adj_factor",
]
