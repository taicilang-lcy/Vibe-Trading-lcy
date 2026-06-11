---
name: data-routing
category: data-source
description: "Data source selection with priority check. MUST call check_data_source tool BEFORE any data-fetching code to get the correct source priority."
---

## ⚠️ IMPORTANT: Always Check Data Source Priority First

**Before writing any data-fetching Python code, you MUST call the `check_data_source` tool.**

```
check_data_source(market="a_share")
```

This returns the recommended source and priority chain based on:
- Whether TUSHARE_TOKEN is configured
- Current time (tushare data updates after 20:00)
- Market type
- Extensions API availability

Example result:
```json
{
  "recommended_source": "tushare",
  "reason": "TUSHARE_TOKEN configured, data updated after 20:00. Use tushare first for accuracy.",
  "priority_chain": ["tushare", "mootdx", "akshare"],
  "current_hour": 21,
  "extensions_hint": "Extensions API available for: moneyflow(资金流向), dragon_tiger(龙虎榜), ..."
}
```

**How to use the result in your Python code:**

```python
# The tool returns recommended_source and priority_chain.
# Write your code to try the recommended source first.

# Example: if recommended_source is "tushare"
import tushare as ts
import os
pro = ts.pro_api(os.environ["TUSHARE_TOKEN"])
df = pro.daily(ts_code="000001.SZ", start_date="20260101")

# If tushare fails, fall back to akshare:
# import akshare as ak
# df = ak.stock_zh_a_hist(symbol="000001", period="daily", start_date="20260101")
```

**DO NOT skip this check.** Without it you may waste time on unavailable sources
or violate the user's configured priority (e.g. ignoring a valid TUSHARE_TOKEN).

---

## Time-Aware Priority Rules (A-shares)

| Current Time | TUSHARE_TOKEN | Priority Chain |
|-------------|---------------|----------------|
| 09:00–20:00 | ✅ Yes | mootdx > akshare > tushare |
| 20:00–次日 | ✅ Yes | tushare > mootdx > akshare |
| Any time | ❌ No | mootdx > akshare |

**Why:** Tushare daily data updates at ~18:00–20:00. Before 20:00, mootdx provides
real-time data via TCP; tushare only has stale data from yesterday.

---

## Data Source Overview

| Source | Markets | Auth Required | Network | Skill |
|--------|---------|---------------|---------|-------|
| tushare | A-shares, funds, futures, macro | Yes (`TUSHARE_TOKEN`) | China network | tushare |
| akshare | A-shares, US, HK, futures, macro, forex | No | Unrestricted | akshare |
| yfinance | US stocks, HK stocks, ETFs | No | Needs Yahoo Finance access | yfinance |
| mootdx | A-shares (real-time) | No | TCP to 通达信 servers | mootdx |
| okx | Crypto (OKX exchange) | No | Needs okx.com access | okx-market |
| ccxt | Crypto (100+ exchanges) | No | Needs exchange access | ccxt |

## Extensions API (Special Data Types)

When the `check_data_source` tool reports Extensions API available, these data types
can be fetched via the Extensions dispatcher (standard Python libraries don't provide them):

| Data Type | Description | Usage |
|-----------|-------------|-------|
| moneyflow | 资金流向 | `fetch("moneyflow", codes=["000001.SZ"])` |
| limit_board | 涨跌停 | `fetch("limit_board", trade_date="20260610")` |
| dragon_tiger | 龙虎榜 | `fetch("dragon_tiger", trade_date="20260610")` |
| margin | 融资融券 | `fetch("margin", trade_date="20260610")` |
| block_trade | 大宗交易 | `fetch("block_trade", trade_date="20260610")` |
| shareholders | 股东户数 | `fetch("shareholders", ts_code="000001.SZ")` |
| adj_factor | 复权因子 | `fetch("adj_factor", ts_code="000001.SZ")` |

**Code pattern:**
```python
from extensions.core.dispatcher import fetch

df = fetch("moneyflow", codes=["000001.SZ"], start_date="20260101")
```

## Decision Tree

### Backtest Scenario (writing config.json)

Use `source: "auto"` — the runner automatically routes by symbol pattern and falls back to alternative sources if the primary one is unavailable.

You do NOT need to specify a concrete data source in config.json unless the user explicitly asks for one.

### Analysis / Research Scenario (writing Python scripts)

1. **Call `check_data_source(market=...)` to get the recommended priority**
2. Write code using the recommended source first
3. Add fallback logic for reliability
4. For Extensions-only data (moneyflow, dragon_tiger, etc.), use `from extensions.core.dispatcher import fetch`

### Availability Check

- **tushare**: `check_data_source` reports `tushare_available`
- **mootdx**: `check_data_source` reports `mootdx_available`
- **yfinance / okx / ccxt / akshare**: free but may have network restrictions
- **Extensions**: `check_data_source` reports `extensions.available`
- If the user reports "connection timeout" or "cannot access", switch to the same-market fallback

## Symbol Format Reference

| Market | Format | Examples |
|--------|--------|---------|
| A-shares | `NNNNNN.SZ/SH/BJ` | 000001.SZ, 600000.SH |
| US stocks | `TICKER.US` | AAPL.US, MSFT.US |
| HK stocks | `NNN(N).HK` | 700.HK, 9988.HK |
| Crypto | `SYMBOL-USDT` | BTC-USDT, ETH-USDT |
| Futures | `XXNNNN.EXCHANGE` | CU2406.SHFE |
| Forex | `XXX/YYY` | USD/CNY, EUR/USD |

## Fallback Chain (Runner Layer)

The backtest runner implements automatic fallback at the market level:

```
User requests 000001.SZ (A-share)
  -> detect market: a_share
  -> try tushare: TUSHARE_TOKEN missing -> skip
  -> try akshare: available -> use akshare
  -> success (zero config required)
```

This is transparent to the user — they just see results.
