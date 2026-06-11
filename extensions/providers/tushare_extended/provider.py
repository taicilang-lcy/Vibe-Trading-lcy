"""Tushare 8000 积分扩展 Provider。

实现以下接口：
- moneyflow: 个股资金流向
- limit_board: 打板数据（limit_list_d）
- dragon_tiger: 龙虎榜（top_list, top_inst）
- margin: 融资融券
- block_trade: 大宗交易
- shareholders: 股东户数
- adj_factor: 复权因子

设计原则：
- 按 trade_date 拉取全市场数据（更高效）
- 内置重试、限流、静默截断验证
- 数据规范化交由 normalizer 处理
"""

from __future__ import annotations

import os
import time
import logging
from typing import Any, Callable, TypeVar

import pandas as pd

from extensions.core.base_provider import (
    DataProvider,
    DataProviderError,
    DataFetchError,
    DEFAULT_RATE_LIMIT_INTERVAL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BACKOFF,
    TRANSIENT_EXCEPTIONS,
)

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

# Token 占位符
TUSHARE_TOKEN_PLACEHOLDERS = {"", "your-tushare-token", "your-tushare-token-here"}


class TushareExtendedProvider(DataProvider):
    """Tushare 8000 积分扩展数据源。

    实现 Tushare Pro API 的扩展接口，包括：
    - 资金流向
    - 打板数据
    - 龙虎榜
    - 融资融券
    - 大宗交易
    - 股东户数
    - 复权因子
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """初始化 Provider。

        Args:
            config: 配置字典，可包含：
                - token_env: token 环境变量名（默认 TUSHARE_TOKEN）
                - retry: 重试次数（默认 3）
                - retry_delay: 重试延迟（默认 0.3）
                - rate_limit_interval: 限流间隔（默认 0.3）
        """
        config = config or {}
        self._config = config

        # 从环境变量获取 token
        token_env = config.get("token_env", "TUSHARE_TOKEN")
        self._token = os.getenv(token_env, "").strip()

        # API 客户端（延迟初始化）
        self._api: Any = None

        # 配置参数
        self._max_retries = config.get("retry", DEFAULT_MAX_RETRIES)
        self._retry_delay = config.get("retry_delay", DEFAULT_RATE_LIMIT_INTERVAL)
        self._rate_limit_interval = config.get(
            "rate_limit_interval", DEFAULT_RATE_LIMIT_INTERVAL
        )

        # 上次 API 调用时间（用于限流）
        self._last_call_time: float = 0.0

    @property
    def name(self) -> str:
        return "tushare_extended"

    @property
    def description(self) -> str:
        return "Tushare 8000 积分扩展数据源"

    @property
    def supported_types(self) -> list[str]:
        return [
            "moneyflow",
            "limit_board",
            "dragon_tiger",
            "margin",
            "block_trade",
            "shareholders",
            "adj_factor",
        ]

    def is_available(self) -> bool:
        """检查 Tushare token 是否可用。"""
        return self._token not in TUSHARE_TOKEN_PLACEHOLDERS

    def _get_api(self) -> Any:
        """获取或初始化 Tushare API 客户端。"""
        if self._api is None:
            try:
                import tushare as ts
                self._api = ts.pro_api(self._token)
            except ImportError as exc:
                raise DataProviderError(
                    "tushare package not installed. Run: pip install tushare"
                ) from exc
        return self._api

    # -------------------------------------------------------------------------
    # 主入口：fetch
    # -------------------------------------------------------------------------

    def fetch(self, data_type: str, **kwargs) -> pd.DataFrame:
        """获取数据。

        Args:
            data_type: 数据类型（见 supported_types）
            **kwargs: 额外参数，常见参数包括：
                - codes: 股票代码列表（可选，某些接口按 trade_date 拉全市场）
                - start_date: 开始日期（YYYY-MM-DD 或 YYYYMMDD）
                - end_date: 结束日期
                - trade_date: 交易日期（用于按日期拉取）

        Returns:
            DataFrame

        Raises:
            DataFetchError: 数据获取失败
        """
        api = self._get_api()

        # 路由到具体方法
        method_map = {
            "moneyflow": self._fetch_moneyflow,
            "limit_board": self._fetch_limit_board,
            "dragon_tiger": self._fetch_dragon_tiger,
            "margin": self._fetch_margin,
            "block_trade": self._fetch_block_trade,
            "shareholders": self._fetch_shareholders,
            "adj_factor": self._fetch_adj_factor,
        }

        method = method_map.get(data_type)
        if method is None:
            raise DataFetchError(f"Unsupported data_type: {data_type}")

        return method(api, **kwargs)

    # -------------------------------------------------------------------------
    # 各接口实现
    # -------------------------------------------------------------------------

    def _fetch_moneyflow(
        self,
        api: Any,
        *,
        codes: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        trade_date: str | None = None,
        **kwargs,
    ) -> pd.DataFrame:
        """获取个股资金流向。

        Tushare 接口：moneyflow
        所需积分：≥2000
        建议：按 trade_date 拉全市场（~5000 次/年），不按 ts_code（~5000 次/股票）

        Args:
            api: Tushare API 客户端
            codes: 股票代码列表（可选）
            start_date: 开始日期（YYYYMMDD）
            end_date: 结束日期（YYYYMMDD）
            trade_date: 交易日期（YYYYMMDD）

        Returns:
            DataFrame，字段包括：
            - ts_code: 股票代码
            - trade_date: 交易日期
            - net_mf_amount: 净流入金额（万元）
            - buy_elg_amount: 超大单买入（万元）
            - sell_elg_amount: 超大单卖出（万元）
            - 等
        """
        params = self._build_params(codes, start_date, end_date, trade_date)

        df = self._call_api_with_retry(
            api.moneyflow,
            label="moneyflow",
            **params
        )

        self.validate_truncation(
            df, source="tushare", data_type="moneyflow", trade_date=trade_date
        )
        return df

    def _fetch_limit_board(
        self,
        api: Any,
        *,
        codes: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        trade_date: str | None = None,
        **kwargs,
    ) -> pd.DataFrame:
        """获取打板数据（涨跌停、炸板）。

        Tushare 接口：limit_list_d
        所需积分：≥5000（8000 无限制）
        建议：按 trade_date 拉全市场

        Args:
            api: Tushare API 客户端
            codes: 股票代码列表（可选）
            start_date: 开始日期（YYYYMMDD）
            end_date: 结束日期（YYYYMMDD）
            trade_date: 交易日期（YYYYMMDD）

        Returns:
            DataFrame，字段包括：
            - ts_code: 股票代码
            - trade_date: 交易日期
            - up_stat: 涨跌停状态（U 涨停/D 跌停）
            - fd_amount: 封单金额（元）
            - 等
        """
        params = self._build_params(codes, start_date, end_date, trade_date)

        df = self._call_api_with_retry(
            api.limit_list_d,
            label="limit_list_d",
            **params
        )

        self.validate_truncation(
            df, source="tushare", data_type="limit_list_d", trade_date=trade_date
        )
        return df

    def _fetch_dragon_tiger(
        self,
        api: Any,
        *,
        codes: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        trade_date: str | None = None,
        **kwargs,
    ) -> pd.DataFrame:
        """获取龙虎榜数据。

        Tushare 接口：top_list, top_inst
        所需积分：≥2000
        建议：按 trade_date 拉全市场

        Args:
            api: Tushare API 客户端
            codes: 股票代码列表（可选）
            start_date: 开始日期（YYYYMMDD）
            end_date: 结束日期（YYYYMMDD）
            trade_date: 交易日期（YYYYMMDD）

        Returns:
            DataFrame，字段包括：
            - ts_code: 股票代码
            - trade_date: 交易日期
            - exalter: 营业部名称
            - buy_amount: 买入金额
            - sell_amount: 卖出金额
            - 等
        """
        params = self._build_params(codes, start_date, end_date, trade_date)

        # 获取龙虎榜列表
        df_list = self._call_api_with_retry(
            api.top_list,
            label="top_list",
            **params
        )

        # 可选：获取机构明细
        if kwargs.get("include_inst", True):
            try:
                df_inst = self._call_api_with_retry(
                    api.top_inst,
                    label="top_inst",
                    **params
                )
                if df_inst is not None and not df_inst.empty:
                    df_list = pd.concat([df_list, df_inst], ignore_index=True)
            except Exception as exc:
                logger.warning("Failed to fetch top_inst: %s", exc)

        self.validate_truncation(
            df_list, source="tushare", data_type="top_list", trade_date=trade_date
        )
        return df_list

    def _fetch_margin(
        self,
        api: Any,
        *,
        codes: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        trade_date: str | None = None,
        **kwargs,
    ) -> pd.DataFrame:
        """获取融资融券数据。

        Tushare 接口：margin, margin_detail
        所需积分：≥2000
        建议：按 trade_date 拉全市场

        Args:
            api: Tushare API 客户端
            codes: 股票代码列表（可选）
            start_date: 开始日期（YYYYMMDD）
            end_date: 结束日期（YYYYMMDD）
            trade_date: 交易日期（YYYYMMDD）

        Returns:
            DataFrame，字段包括：
            - ts_code: 股票代码
            - trade_date: 交易日期
            - rzye: 融资余额（元）
            - rqye: 融券余额（元）
            - 等
        """
        params = self._build_params(codes, start_date, end_date, trade_date)

        df = self._call_api_with_retry(
            api.margin,
            label="margin",
            **params
        )

        self.validate_truncation(
            df, source="tushare", data_type="margin", trade_date=trade_date
        )
        return df

    def _fetch_block_trade(
        self,
        api: Any,
        *,
        codes: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        trade_date: str | None = None,
        **kwargs,
    ) -> pd.DataFrame:
        """获取大宗交易数据。

        Tushare 接口：block_trade
        所需积分：≥2000
        建议：按 trade_date 拉全市场

        Args:
            api: Tushare API 客户端
            codes: 股票代码列表（可选）
            start_date: 开始日期（YYYYMMDD）
            end_date: 结束日期（YYYYMMDD）
            trade_date: 交易日期（YYYYMMDD）

        Returns:
            DataFrame，字段包括：
            - ts_code: 股票代码
            - trade_date: 交易日期
            - trade_price: 成交价
            - trade_vol: 成交量
            - trade_amount: 成交金额
            - buyer_name: 买方营业部
            - seller_name: 卖方营业部
            - 等
        """
        params = self._build_params(codes, start_date, end_date, trade_date)

        df = self._call_api_with_retry(
            api.block_trade,
            label="block_trade",
            **params
        )

        self.validate_truncation(
            df, source="tushare", data_type="block_trade", trade_date=trade_date
        )
        return df

    def _fetch_shareholders(
        self,
        api: Any,
        *,
        codes: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        trade_date: str | None = None,
        **kwargs,
    ) -> pd.DataFrame:
        """获取股东户数数据。

        Tushare 接口：stk_holdernumber
        所需积分：≥2000
        建议：按 ts_code 拉取（更新频率为季度）

        Args:
            api: Tushare API 客户端
            codes: 股票代码列表（必须）
            start_date: 开始日期（YYYYMMDD）
            end_date: 结束日期（YYYYMMDD）
            trade_date: 交易日期（YYYYMMDD）

        Returns:
            DataFrame，字段包括：
            - ts_code: 股票代码
            - ann_date: 公告日期
            - end_date: 截止日期
            - holder_num: 股东户数
            - 等
        """
        # 股东户数需要按 ts_code 拉取
        if codes is None or len(codes) == 0:
            logger.warning("shareholders requires codes parameter")
            return pd.DataFrame()

        frames: list[pd.DataFrame] = []
        for code in codes:
            params = {"ts_code": code}
            if start_date:
                params["start_date"] = self._format_date(start_date)
            if end_date:
                params["end_date"] = self._format_date(end_date)

            df = self._call_api_with_retry(
                api.stk_holdernumber,
                label=f"stk_holdernumber_{code}",
                **params
            )
            if df is not None and not df.empty:
                frames.append(df)

        if not frames:
            return pd.DataFrame()

        result = pd.concat(frames, ignore_index=True)
        self.validate_truncation(
            result, source="tushare", data_type="stk_holdernumber"
        )
        return result

    def _fetch_adj_factor(
        self,
        api: Any,
        *,
        codes: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        trade_date: str | None = None,
        **kwargs,
    ) -> pd.DataFrame:
        """获取复权因子数据。

        Tushare 接口：adj_factor
        所需积分：基础（无限制）
        建议：按 trade_date 拉全市场

        Args:
            api: Tushare API 客户端
            codes: 股票代码列表（可选）
            start_date: 开始日期（YYYYMMDD）
            end_date: 结束日期（YYYYMMDD）
            trade_date: 交易日期（YYYYMMDD）

        Returns:
            DataFrame，字段包括：
            - ts_code: 股票代码
            - trade_date: 交易日期
            - adj_factor: 复权因子
        """
        params = self._build_params(codes, start_date, end_date, trade_date)

        df = self._call_api_with_retry(
            api.adj_factor,
            label="adj_factor",
            **params
        )

        self.validate_truncation(
            df, source="tushare", data_type="adj_factor", trade_date=trade_date
        )
        return df

    # -------------------------------------------------------------------------
    # 辅助方法
    # -------------------------------------------------------------------------

    def _build_params(
        self,
        codes: list[str] | None,
        start_date: str | None,
        end_date: str | None,
        trade_date: str | None,
    ) -> dict[str, Any]:
        """构建 API 参数。

        优先使用 trade_date（全市场拉取更高效），其次使用 ts_code + 日期范围。
        """
        params: dict[str, Any] = {}

        if trade_date:
            params["trade_date"] = self._format_date(trade_date)
        elif codes and len(codes) == 1:
            params["ts_code"] = codes[0]
            if start_date:
                params["start_date"] = self._format_date(start_date)
            if end_date:
                params["end_date"] = self._format_date(end_date)
        else:
            # 多只股票：按日期范围拉全市场
            if start_date:
                params["start_date"] = self._format_date(start_date)
            if end_date:
                params["end_date"] = self._format_date(end_date)

        return params

    def _format_date(self, date_str: str) -> str:
        """格式化日期为 YYYYMMDD 格式。"""
        if not date_str:
            return date_str
        # 移除分隔符
        return date_str.replace("-", "").replace("/", "")[:8]

    def _call_api_with_retry(
        self,
        api_func: Callable[..., _T],
        label: str,
        **kwargs,
    ) -> _T:
        """带限流和重试的 API 调用。

        确保调用间隔 ≥ rate_limit_interval 秒。
        """
        # 限流：确保调用间隔
        elapsed = time.monotonic() - self._last_call_time
        if elapsed < self._rate_limit_interval:
            time.sleep(self._rate_limit_interval - elapsed)

        for attempt in range(self._max_retries + 1):
            try:
                self._last_call_time = time.monotonic()
                result = api_func(**kwargs)
                return result

            except TRANSIENT_EXCEPTIONS as exc:
                if attempt == self._max_retries:
                    raise TimeoutError(
                        f"{label} failed after {attempt + 1} attempt(s): {exc}"
                    ) from exc

                # 退避重试
                wait_time = DEFAULT_RETRY_BACKOFF[min(attempt, len(DEFAULT_RETRY_BACKOFF) - 1)]
                logger.warning(
                    "%s: transient error on attempt %d/%d, retrying in %.1fs: %s",
                    label, attempt + 1, self._max_retries + 1, wait_time, exc
                )
                time.sleep(wait_time)

            except Exception as exc:
                raise DataFetchError(f"{label} failed: {exc}") from exc

        raise AssertionError("unreachable: retry loop must return or raise")
