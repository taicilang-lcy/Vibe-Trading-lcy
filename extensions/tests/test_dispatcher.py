"""测试 dispatcher 模块。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from extensions.core.dispatcher import (
    DataDispatcher,
    get_dispatcher,
    fetch,
    DEFAULT_CONFIG_PATH,
)


class TestDataDispatcher:
    """DataDispatcher 测试。"""

    def test_init_with_default_config(self, tmp_path, monkeypatch) -> None:
        """测试使用默认配置初始化。"""
        # 不存在配置文件时使用默认配置
        dispatcher = DataDispatcher(config_path=tmp_path / "nonexistent.yaml")

        assert "moneyflow" in dispatcher.list_types()
        assert "limit_board" in dispatcher.list_types()

    def test_list_types(self) -> None:
        """测试列出数据类型。"""
        dispatcher = DataDispatcher(config_path=Path("/nonexistent"))

        types = dispatcher.list_types()

        assert "moneyflow" in types
        assert "limit_board" in types
        assert "dragon_tiger" in types
        assert "margin" in types
        assert "block_trade" in types
        assert "shareholders" in types
        assert "adj_factor" in types

    def test_list_providers(self) -> None:
        """测试列出 Provider。"""
        dispatcher = DataDispatcher(config_path=Path("/nonexistent"))

        # Provider 初始化可能失败（无 token），所以只检查方法不抛异常
        providers = dispatcher.list_providers()
        assert isinstance(providers, list)

    def test_fetch_no_routing(self) -> None:
        """测试无路由配置时抛出异常。"""
        dispatcher = DataDispatcher(config_path=Path("/nonexistent"))
        dispatcher.type_routing = {}  # 清空路由

        with pytest.raises(Exception):  # NoAvailableProviderError
            dispatcher.fetch("unknown_type")

    def test_fetch_all_providers_unavailable(self, monkeypatch) -> None:
        """测试所有 Provider 不可用时抛出异常。"""
        dispatcher = DataDispatcher(config_path=Path("/nonexistent"))

        # Mock 所有 Provider 不可用
        monkeypatch.setattr(dispatcher, "providers", {})

        with pytest.raises(Exception):  # NoAvailableProviderError
            dispatcher.fetch("moneyflow")


class TestGlobalDispatcher:
    """全局调度器测试。"""

    def test_get_dispatcher_singleton(self) -> None:
        """测试全局单例。"""
        # 重置单例
        import extensions.core.dispatcher as d
        d._dispatcher = None

        d1 = get_dispatcher()
        d2 = get_dispatcher()

        assert d1 is d2

    def test_fetch_convenience_function(self, monkeypatch) -> None:
        """测试便捷函数。"""
        import extensions.core.dispatcher as d
        d._dispatcher = None

        mock_dispatcher = MagicMock()
        mock_dispatcher.fetch.return_value = pd.DataFrame({"col": [1]})

        monkeypatch.setattr(d, "get_dispatcher", lambda: mock_dispatcher)

        result = fetch("moneyflow", codes=["000001.SZ"])

        mock_dispatcher.fetch.assert_called_once()
        assert isinstance(result, pd.DataFrame)


class TestConfigLoading:
    """配置加载测试。"""

    def test_default_config_values(self, tmp_path) -> None:
        """测试默认配置值。"""
        dispatcher = DataDispatcher(config_path=tmp_path / "nonexistent.yaml")

        assert dispatcher.config["normalization"]["volume_unit"] == "shares"
        assert dispatcher.config["normalization"]["amount_unit"] == "cny"
        assert dispatcher.config["normalization"]["market_cap_unit"] == "yi_cny"

    def test_yaml_config_loading(self, tmp_path) -> None:
        """测试 YAML 配置加载。"""
        config_content = """
providers:
  test_provider:
    enabled: false

data_type_routing:
  test_type: [test_provider]

normalization:
  volume_unit: lots
"""
        config_path = tmp_path / "test_config.yaml"
        config_path.write_text(config_content, encoding="utf-8")

        dispatcher = DataDispatcher(config_path=config_path)

        assert "test_type" in dispatcher.type_routing
        assert dispatcher.config["normalization"]["volume_unit"] == "lots"
