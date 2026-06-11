"""所有数据 Provider 的标准接口。

每个 Provider 必须实现：
1. name / description / supported_types — 静态元数据
2. is_available() — 检查凭证/网络是否可用
3. fetch() — 核心数据获取方法

扩展层的设计原则：
- 不修改 agent/ 下任何上游文件
- 所有 Provider 继承此标准接口
- 数据获取后通过 normalizer.py 统一单位换算
"""

from __future__ import annotations

import time
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, TypeVar

import pandas as pd

logger = logging.getLogger(__name__)

# Tushare 8000 积分限流参数：500 次/分钟，间隔 ≥ 0.3s
DEFAULT_RATE_LIMIT_INTERVAL = 0.3  # 秒
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF = (1.0, 2.0, 4.0)  # 秒

# 瞬态异常类型（可重试）
TRANSIENT_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    OSError,  # 网络相关错误
)

_T = TypeVar("_T")


class DataProviderError(Exception):
    """Provider 相关错误的基类。"""


class NoAvailableProviderError(DataProviderError):
    """没有可用的 Provider 时抛出。"""


class DataFetchError(DataProviderError):
    """数据获取失败时抛出。"""


class SilentTruncationWarning(DataProviderError):
    """静默截断检测：返回数据量低于预期时抛出（作为警告，不中断流程）。"""


class DataProvider(ABC):
    """数据源 Provider 基类。

    每个 Provider 必须实现以下抽象方法：
    - name: Provider 唯一标识
    - description: 中文描述
    - supported_types: 支持的数据类型列表
    - is_available(): 检查可用性
    - fetch(): 获取数据

    此外，基类提供：
    - fetch_with_retry(): 带限流和重试的 API 调用
    - validate_truncation(): 静默截断验证
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 唯一标识，如 'tushare_extended'"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """中文描述"""
        ...

    @property
    @abstractmethod
    def supported_types(self) -> list[str]:
        """支持的数据类型列表，如 ['moneyflow', 'limit_board']"""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """检查 Provider 是否可用（token 有效、网络连通等）"""
        ...

    @abstractmethod
    def fetch(self, data_type: str, **kwargs) -> pd.DataFrame:
        """获取数据。返回 DataFrame（字段由 Normalizer 统一）"""
        ...

    # -------------------------------------------------------------------------
    # 共享工具方法
    # -------------------------------------------------------------------------

    def fetch_with_retry(
        self,
        api_func: Callable[..., _T],
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        interval: float = DEFAULT_RATE_LIMIT_INTERVAL,
        backoff: tuple[float, ...] = DEFAULT_RETRY_BACKOFF,
        deadline: float | None = None,
        label: str = "fetch",
        **kwargs,
    ) -> _T:
        """带限流和重试的 API 调用。

        扩展层所有 Provider 统一使用此函数，确保：
        1. 限流：每次调用间隔 ≥ interval 秒
        2. 重试：瞬态异常最多重试 max_retries 次
        3. 退避：重试间隔按 backoff 递增
        4. 超时：可选的 wall-clock deadline

        Args:
            api_func: API 调用函数
            max_retries: 最大重试次数
            interval: 限流间隔（秒）
            backoff: 重试退避序列
            deadline: 可选的超时时间点（time.monotonic()）
            label: 用于日志和错误消息的标签
            **kwargs: 传递给 api_func 的参数

        Returns:
            api_func 的返回值

        Raises:
            TimeoutError: 重试耗尽或超时
            DataFetchError: 非 transient 异常
        """
        if len(backoff) < max_retries:
            backoff = tuple(list(backoff) * (max_retries // len(backoff) + 1))

        for attempt in range(max_retries + 1):
            try:
                # 限流：确保调用间隔
                time.sleep(interval)
                result = api_func(**kwargs)
                return result

            except TRANSIENT_EXCEPTIONS as exc:
                remaining = deadline - time.monotonic() if deadline else float("inf")
                if attempt == max_retries or remaining <= 0:
                    raise TimeoutError(
                        f"{label} failed after {attempt + 1} attempt(s): {exc}"
                    ) from exc

                # 退避重试，但不超过剩余时间
                wait_time = min(backoff[attempt], max(0.0, remaining))
                logger.warning(
                    "%s: transient error on attempt %d/%d, retrying in %.1fs: %s",
                    label, attempt + 1, max_retries + 1, wait_time, exc
                )
                time.sleep(wait_time)

            except Exception as exc:
                # 非瞬态异常直接抛出
                raise DataFetchError(f"{label} failed with non-transient error: {exc}") from exc

        raise AssertionError("unreachable: retry loop must return or raise")

    def validate_truncation(
        self,
        df: pd.DataFrame,
        *,
        expected_min_rows: int | None = None,
        source: str = "unknown",
        data_type: str = "unknown",
        trade_date: str | None = None,
    ) -> None:
        """验证静默截断。

        Tushare API 无分页参数，超限不报错：
        - 财务数据 ~1000 行
        - 日线数据 ~5000 行

        此方法用于检测可能的静默截断，发出警告日志但不中断流程。

        Args:
            df: 返回的 DataFrame
            expected_min_rows: 预期最小行数（可选）
            source: 数据源名称
            data_type: 数据类型
            trade_date: 交易日期（用于日志）
        """
        if df is None or df.empty:
            return

        row_count = len(df)

        # Tushare 已知的截断阈值
        truncation_thresholds = {
            "moneyflow": 5000,  # 全市场日级资金流
            "margin": 5000,     # 全市场融资融券
            "block_trade": 1000,  # 大宗交易
            "top_list": 1000,   # 龙虎榜
            "limit_list_d": 5000,  # 打板数据
            "stk_holdernumber": 1000,  # 股东户数
            "adj_factor": 5000,  # 复权因子
        }

        threshold = truncation_thresholds.get(data_type, 5000)
        if expected_min_rows is not None:
            threshold = max(threshold, expected_min_rows)

        # 接近阈值时发出警告
        if row_count >= threshold * 0.9:
            logger.warning(
                "Silent truncation suspected: %s.%s returned %d rows (threshold ~%d). "
                "trade_date=%s. Consider splitting requests by trade_date.",
                source, data_type, row_count, threshold, trade_date or "N/A"
            )


class ProviderRegistry:
    """Provider 注册中心。

    管理 Provider 实例，支持按数据类型查找。
    """

    def __init__(self) -> None:
        self._providers: dict[str, DataProvider] = {}
        self._type_to_providers: dict[str, list[str]] = {}

    def register(self, provider: DataProvider) -> None:
        """注册一个 Provider。"""
        self._providers[provider.name] = provider
        for data_type in provider.supported_types:
            if data_type not in self._type_to_providers:
                self._type_to_providers[data_type] = []
            self._type_to_providers[data_type].append(provider.name)

    def get(self, name: str) -> DataProvider | None:
        """按名称获取 Provider。"""
        return self._providers.get(name)

    def get_for_type(self, data_type: str) -> list[DataProvider]:
        """按数据类型获取可用的 Provider 列表。"""
        names = self._type_to_providers.get(data_type, [])
        return [self._providers[n] for n in names if n in self._providers]

    def list_all(self) -> list[str]:
        """列出所有已注册的 Provider 名称。"""
        return list(self._providers.keys())

    def list_types(self) -> list[str]:
        """列出所有已注册的数据类型。"""
        return list(self._type_to_providers.keys())