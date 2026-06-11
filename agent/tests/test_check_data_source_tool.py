"""Tests for check_data_source_tool.

TDD — tests define expected behaviour for the refactored tool.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch
from contextlib import contextmanager

import pytest

from src.tools.check_data_source_tool import (
    CheckDataSourceTool,
    check_data_source,
    _TOKEN_PLACEHOLDERS,
)
from src.agent.tools import BaseTool
from backtest.loaders.registry import FALLBACK_CHAINS


# ---------------------------------------------------------------------------
# Patching helpers
# ---------------------------------------------------------------------------

@contextmanager
def _patch_env(**kwargs):
    """Temporarily set environment variables."""
    saved = {}
    for k, v in kwargs.items():
        saved[k] = os.environ.get(k)
        os.environ[k] = v
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextmanager
def _patch_hour(hour: int):
    """Patch datetime.now() to return a specific hour."""
    with patch("src.tools.check_data_source_tool.datetime") as mock_dt:
        mock_now = MagicMock()
        mock_now.hour = hour
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        yield


@contextmanager
def _patch_mootdx(available: bool):
    """Patch mootdx availability check directly."""
    with patch("src.tools.check_data_source_tool._check_mootdx", return_value=available):
        yield


@contextmanager
def _patch_extensions(available: bool, types: list[str] | None = None):
    """Patch extensions dispatcher check."""
    if available:
        mock_dispatcher = MagicMock()
        mock_dispatcher.list_providers.return_value = ["tushare_extended"]
        mock_dispatcher.list_types.return_value = types or ["moneyflow", "dragon_tiger"]
        mock_module = MagicMock()
        mock_module.get_dispatcher.return_value = mock_dispatcher
        with patch.dict(sys.modules, {
            "extensions": mock_module,
            "extensions.core": mock_module,
            "extensions.core.dispatcher": mock_module,
        }):
            yield
    else:
        with patch.dict(sys.modules, {
            "extensions": None,
            "extensions.core": None,
            "extensions.core.dispatcher": None,
        }):
            yield


def _call(market: str = "a_share") -> dict:
    """Call check_data_source and return parsed result."""
    return json.loads(CheckDataSourceTool().execute(market=market))


# ===========================================================================
# 1. FALLBACK_CHAINS deduplication — tool must NOT duplicate registry chains
# ===========================================================================

class TestFallbackChainsDedup:

    def test_no_hardcoded_market_chains(self):
        """_MARKET_CHAINS must not exist — use registry instead."""
        import src.tools.check_data_source_tool as mod
        assert not hasattr(mod, "_MARKET_CHAINS"), (
            "_MARKET_CHAINS is still hardcoded — tool should import "
            "FALLBACK_CHAINS from backtest.loaders.registry instead"
        )

    def test_no_hardcoded_extensions_types(self):
        """_EXTENSIONS_TYPES must not exist — labels come from dispatcher."""
        import src.tools.check_data_source_tool as mod
        assert not hasattr(mod, "_EXTENSIONS_TYPES"), (
            "_EXTENSIONS_TYPES is still hardcoded — labels should come from "
            "the dispatcher or be omitted"
        )

    def test_a_share_chain_matches_registry(self):
        """After 20:00 with token, a_share chain == registry chain."""
        with _patch_env(TUSHARE_TOKEN="valid-token"), \
             _patch_hour(21), _patch_mootdx(True), _patch_extensions(False):
            result = _call("a_share")
        assert result["priority_chain"] == list(FALLBACK_CHAINS["a_share"])

    def test_us_equity_chain_matches_registry(self):
        with _patch_env(TUSHARE_TOKEN="valid-token"), \
             _patch_hour(14), _patch_extensions(False):
            result = _call("us_equity")
        assert result["priority_chain"] == list(FALLBACK_CHAINS["us_equity"])

    def test_crypto_chain_matches_registry(self):
        """crypto chain must match registry (includes yfinance)."""
        with _patch_env(TUSHARE_TOKEN=""), \
             _patch_hour(14), _patch_extensions(False):
            result = _call("crypto")
        # No token → tushare removed, but crypto chain has no tushare anyway
        assert result["priority_chain"] == list(FALLBACK_CHAINS["crypto"])


# ===========================================================================
# 2. Extensions: types from dispatcher, not hardcoded
# ===========================================================================

class TestExtensionsFromDispatcher:

    def test_extensions_types_reflect_dispatcher(self):
        """data_types must come from the dispatcher, not a hardcoded list."""
        custom_types = ["moneyflow", "dragon_tiger", "new_future_type"]
        with _patch_extensions(True, types=custom_types), \
             _patch_env(TUSHARE_TOKEN=""), _patch_hour(14):
            result = _call()
        assert result["extensions_data_types"] == custom_types


# ===========================================================================
# 3. Exceptions logged, not silently swallowed
# ===========================================================================

class TestExceptionsLogged:

    def test_extensions_failure_logged(self, caplog):
        """When extensions import fails, a warning/debug must be logged."""
        with _patch_extensions(False), \
             _patch_env(TUSHARE_TOKEN=""), _patch_hour(14):
            with caplog.at_level("DEBUG"):
                result = _call()
        assert result["extensions_available"] is False
        # Must have logged something (debug or warning) about dispatcher
        assert any(
            "dispatcher" in r.message.lower() or "extensions" in r.message.lower()
            for r in caplog.records
        )


# ===========================================================================
# 4. Return structure — flat, lean, no nested dicts
# ===========================================================================

class TestReturnStructure:

    def test_no_nested_dicts(self):
        """No nested dicts — flat structure is easier for LLM."""
        with _patch_env(TUSHARE_TOKEN=""), _patch_hour(14), \
             _patch_extensions(False):
            result = _call()
        for k, v in result.items():
            assert not isinstance(v, dict), (
                f"Nested dict at key '{k}' — flatten for LLM readability"
            )

    def test_max_9_top_level_keys(self):
        """Return should be compact, not bloated."""
        with _patch_env(TUSHARE_TOKEN=""), _patch_hour(14), \
             _patch_extensions(False):
            result = _call()
        assert len(result) <= 9, (
            f"{len(result)} keys is too many. Keys: {sorted(result.keys())}"
        )

    def test_essential_keys(self):
        """Must always have recommended_source, reason, priority_chain, current_hour."""
        with _patch_env(TUSHARE_TOKEN=""), _patch_hour(14), \
             _patch_extensions(False):
            result = _call()
        for key in ("recommended_source", "reason", "priority_chain", "current_hour"):
            assert key in result, f"Missing essential key: {key}"


# ===========================================================================
# 5. A-share time-aware priority logic
# ===========================================================================

class TestAShareTimeAwarePriority:

    def test_after_20_with_token_tushare_first(self):
        with _patch_env(TUSHARE_TOKEN="valid-token"), \
             _patch_hour(21), _patch_mootdx(True), _patch_extensions(False):
            r = _call("a_share")
        assert r["recommended_source"] == "tushare"
        assert r["priority_chain"][0] == "tushare"

    def test_before_20_with_token_tushare_last(self):
        with _patch_env(TUSHARE_TOKEN="valid-token"), \
             _patch_hour(14), _patch_mootdx(True), _patch_extensions(False):
            r = _call("a_share")
        assert r["recommended_source"] == "mootdx"
        assert r["priority_chain"][-1] == "tushare"

    def test_before_20_no_mootdx_with_token(self):
        with _patch_env(TUSHARE_TOKEN="valid-token"), \
             _patch_hour(14), _patch_mootdx(False), _patch_extensions(False):
            r = _call("a_share")
        assert r["recommended_source"] == "akshare"
        assert r["priority_chain"][-1] == "tushare"

    def test_no_token_mootdx_first(self):
        with _patch_env(TUSHARE_TOKEN=""), \
             _patch_hour(21), _patch_mootdx(True), _patch_extensions(False):
            r = _call("a_share")
        assert r["recommended_source"] == "mootdx"
        assert "tushare" not in r["priority_chain"]

    def test_no_token_no_mootdx_akshare_only(self):
        with _patch_env(TUSHARE_TOKEN=""), \
             _patch_hour(14), _patch_mootdx(False), _patch_extensions(False):
            r = _call("a_share")
        assert r["recommended_source"] == "akshare"
        assert r["priority_chain"] == ["akshare"]

    def test_exactly_hour_20_is_after(self):
        with _patch_env(TUSHARE_TOKEN="valid-token"), \
             _patch_hour(20), _patch_mootdx(True), _patch_extensions(False):
            r = _call("a_share")
        assert r["recommended_source"] == "tushare"


# ===========================================================================
# 6. Other markets — follow registry chains
# ===========================================================================

class TestOtherMarkets:

    @pytest.mark.parametrize("market", [
        "us_equity", "hk_equity", "crypto", "futures", "fund", "macro", "forex",
    ])
    def test_chain_matches_registry_minus_tushare_when_no_token(self, market):
        """Without token, chain = registry chain minus tushare entries."""
        with _patch_env(TUSHARE_TOKEN=""), _patch_hour(14), \
             _patch_extensions(False):
            result = _call(market)
        expected = [s for s in FALLBACK_CHAINS[market] if s != "tushare"]
        if not expected:
            expected = list(FALLBACK_CHAINS[market])
        assert result["priority_chain"] == expected


# ===========================================================================
# 7. Edge cases
# ===========================================================================

class TestEdgeCases:

    def test_unknown_market_falls_back_to_a_share(self):
        with _patch_env(TUSHARE_TOKEN=""), _patch_hour(14), \
             _patch_mootdx(True), _patch_extensions(False):
            r = _call("mars_stocks")
        assert r["market"] == "a_share"

    def test_placeholder_token_treated_as_missing(self):
        with _patch_env(TUSHARE_TOKEN="your-tushare-token"), \
             _patch_hour(21), _patch_mootdx(True), _patch_extensions(False):
            r = _call("a_share")
        assert r["recommended_source"] == "mootdx"
        assert "tushare" not in r["priority_chain"]

    def test_default_market_is_a_share(self):
        with _patch_env(TUSHARE_TOKEN=""), _patch_hour(14), \
             _patch_mootdx(True), _patch_extensions(False):
            r = _call()
        assert r["market"] == "a_share"


# ===========================================================================
# 8. BaseTool interface compliance
# ===========================================================================

class TestToolInterface:

    def test_is_basetool_subclass(self):
        assert issubclass(CheckDataSourceTool, BaseTool)

    def test_name(self):
        assert CheckDataSourceTool().name == "check_data_source"

    def test_readonly(self):
        assert CheckDataSourceTool().is_readonly is True

    def test_repeatable(self):
        assert CheckDataSourceTool().repeatable is True

    def test_schema_valid(self):
        schema = CheckDataSourceTool().to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "check_data_source"
        assert "market" in schema["function"]["parameters"]["properties"]

    def test_execute_returns_valid_json(self):
        with _patch_env(TUSHARE_TOKEN=""), _patch_hour(14), \
             _patch_extensions(False):
            result_str = CheckDataSourceTool().execute(market="a_share")
        data = json.loads(result_str)
        assert "recommended_source" in data
        assert "priority_chain" in data
