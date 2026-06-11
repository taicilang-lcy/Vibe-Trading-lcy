"""Data source priority checker for Agent ad-hoc mode.

Returns the recommended data source and priority chain based on:
- Whether TUSHARE_TOKEN is configured
- Current hour (tushare data updates after 20:00)
- Market type (a_share, us_equity, hk_equity, crypto, …)
- Extensions dispatcher availability (moneyflow, dragon_tiger, etc.)

The Agent should call this tool BEFORE writing any data-fetching Python code
so it picks the right source instead of guessing.

Single source of truth: FALLBACK_CHAINS are imported from
``backtest.loaders.registry`` — never duplicated here.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

from src.agent.tools import BaseTool

logger = logging.getLogger(__name__)

# Placeholder tokens that should be treated as "not configured".
# Kept as a safety net — the onboarding wizard may write these sentinel
# values when the user skips token entry.
_TOKEN_PLACEHOLDERS = frozenset({
    "", "your-tushare-token", "your_token_here", "xxx",
    "placeholder", "test_token",
})


# ---------------------------------------------------------------------------
# Lazy imports — avoid hard dependency on registry or extensions
# ---------------------------------------------------------------------------

def _get_fallback_chains() -> dict[str, list[str]]:
    """Load FALLBACK_CHAINS from the canonical source of truth.

    Returns an empty dict if the registry module is unavailable (e.g.
    during isolated testing).
    """
    try:
        from backtest.loaders.registry import FALLBACK_CHAINS
        return dict(FALLBACK_CHAINS)
    except ImportError:
        logger.debug("backtest.loaders.registry not importable, using empty chains")
        return {}


def _check_tushare_token() -> bool:
    """Return True if a valid TUSHARE_TOKEN is configured."""
    token = os.getenv("TUSHARE_TOKEN", "").strip()
    return bool(token) and token not in _TOKEN_PLACEHOLDERS


def _check_mootdx() -> bool:
    """Return True if mootdx package is importable.

    Uses importlib.util.find_spec to avoid side-effect imports
    (a bare ``import mootdx`` actually loads the package, which we
    don't need just to check availability).
    """
    import importlib.util
    return importlib.util.find_spec("mootdx") is not None


def _check_extensions() -> tuple[bool, list[str]]:
    """Check Extensions dispatcher availability.

    Returns:
        (available, data_types) tuple.
        Logs warnings on failure instead of silently swallowing exceptions.
    """
    try:
        from extensions.core.dispatcher import get_dispatcher
        d = get_dispatcher()
        return True, d.list_types()
    except ImportError:
        logger.debug("extensions.core.dispatcher not available")
        return False, []
    except Exception as exc:
        logger.warning("Extensions dispatcher check failed: %s", exc)
        return False, []


# ---------------------------------------------------------------------------
# Core routing logic
# ---------------------------------------------------------------------------

def _filter_unavailable(
    chain: list[str],
    *,
    tushare_available: bool,
    mootdx_available: bool,
) -> list[str]:
    """Remove sources that are confirmed unavailable at runtime.

    Only mootdx and tushare need runtime checks — all other sources
    (akshare, yfinance, okx, ccxt, futu) are free and assumed available.
    """
    unavailable: set[str] = set()
    if not tushare_available:
        unavailable.add("tushare")
    if not mootdx_available:
        unavailable.add("mootdx")
    if not unavailable:
        return chain
    return [s for s in chain if s not in unavailable]


def _chain_for_a_share(
    *,
    registry_chain: list[str],
    tushare_available: bool,
    mootdx_available: bool,
    hour: int,
) -> tuple[list[str], str]:
    """Return (priority_chain, reason) for A-share market with time awareness.

    The registry chain is the canonical ordering. This function reorders it
    based on time-of-day and token availability rather than inventing its own
    chain from scratch, then removes sources unavailable at runtime.
    """
    # Step 1: Build policy chain (time-aware ordering)
    if not tushare_available:
        # No token: drop tushare from the policy chain
        chain = [s for s in registry_chain if s != "tushare"]
        if not chain:
            chain = ["akshare"]
        reason = "No TUSHARE_TOKEN. " + " > ".join(chain)
    elif hour >= 20:
        # After 20:00 tushare data is updated — keep registry order as-is
        chain = list(registry_chain)
        reason = (
            "TUSHARE_TOKEN configured, data updated after 20:00. "
            "Use tushare first for accuracy."
        )
    else:
        # Before 20:00 tushare is stale — demote it to last
        chain = [s for s in registry_chain if s != "tushare"]
        chain.append("tushare")
        reason = (
            f"Current hour is {hour}:00, tushare daily data not updated yet. "
            "Prioritize real-time sources, tushare as fallback."
        )

    # Step 2: Filter out sources unavailable at runtime (e.g. mootdx not installed)
    chain = _filter_unavailable(
        chain, tushare_available=tushare_available, mootdx_available=mootdx_available,
    )
    if not chain:
        chain = ["akshare"]

    return chain, reason


def _chain_for_market(
    market: str,
    *,
    registry_chain: list[str],
    tushare_available: bool,
    mootdx_available: bool,
) -> tuple[list[str], str]:
    """Return (priority_chain, reason) for non-A-share markets.

    Uses the registry chain, removes tushare if no token configured,
    then filters out sources unavailable at runtime.
    """
    if tushare_available:
        chain = list(registry_chain)
    else:
        chain = [s for s in registry_chain if s != "tushare"]
        if not chain:
            chain = list(registry_chain)

    # Filter out sources unavailable at runtime
    chain = _filter_unavailable(
        chain, tushare_available=tushare_available, mootdx_available=mootdx_available,
    )
    if not chain:
        chain = list(registry_chain)

    reason = (
        f"Market: {market}. "
        + ("TUSHARE_TOKEN configured. " if tushare_available else "No TUSHARE_TOKEN. ")
        + f"Priority: {' > '.join(chain)}"
    )
    return chain, reason


def check_data_source(market: str = "a_share") -> dict[str, Any]:
    """Check and return the recommended data source priority.

    Core logic separated from BaseTool for testability.

    Args:
        market: Market type key (a_share, us_equity, hk_equity, etc.).

    Returns:
        Flat dict with recommended_source, reason, priority_chain,
        current_hour, and extensions info.
    """
    market = market.lower().strip()

    # Load canonical fallback chains from registry
    fallback_chains = _get_fallback_chains()

    # If unknown market or no chains loaded, default to a_share
    if market not in fallback_chains:
        market = "a_share"
    registry_chain = fallback_chains.get(market, ["akshare"])

    hour = datetime.now().hour
    tushare_available = _check_tushare_token()
    mootdx_available = _check_mootdx()
    extensions_available, extensions_data_types = _check_extensions()

    # Build priority chain
    if market == "a_share":
        chain, reason = _chain_for_a_share(
            registry_chain=registry_chain,
            tushare_available=tushare_available,
            mootdx_available=mootdx_available,
            hour=hour,
        )
    else:
        chain, reason = _chain_for_market(
            market,
            registry_chain=registry_chain,
            tushare_available=tushare_available,
            mootdx_available=mootdx_available,
        )

    recommended = chain[0] if chain else "akshare"

    # Build a compact hint for extensions-only data
    extensions_hint = ""
    if extensions_available and extensions_data_types:
        extensions_hint = (
            "Extensions API available for: "
            + ", ".join(extensions_data_types)
            + ". Use `from extensions.core.dispatcher import fetch`."
        )

    return {
        "recommended_source": recommended,
        "reason": reason,
        "priority_chain": chain,
        "current_hour": hour,
        "market": market,
        "tushare_available": tushare_available,
        "extensions_available": extensions_available,
        "extensions_data_types": extensions_data_types,
        "extensions_hint": extensions_hint,
    }


# ---------------------------------------------------------------------------
# BaseTool interface
# ---------------------------------------------------------------------------

class CheckDataSourceTool(BaseTool):
    """Check the recommended data source and priority chain.

    Call this BEFORE writing any data-fetching Python code so the correct
    source is used first, avoiding wasted retries on unavailable APIs.
    """

    name = "check_data_source"
    description = (
        "Check the recommended data source and priority chain for data fetching. "
        "ALWAYS call this BEFORE writing any Python code that imports tushare/akshare/mootdx. "
        "Returns which source to try first based on TUSHARE_TOKEN, current hour, and market. "
        "Also reports Extensions API availability for moneyflow/dragon_tiger/etc."
    )
    parameters = {
        "type": "object",
        "properties": {
            "market": {
                "type": "string",
                "description": (
                    "Market type. One of: a_share, us_equity, hk_equity, "
                    "crypto, futures, fund, macro, forex. Default: a_share"
                ),
            },
        },
        "required": [],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        market = kwargs.get("market", "a_share")
        result = check_data_source(market=market)
        return json.dumps(result, ensure_ascii=False, default=str)
