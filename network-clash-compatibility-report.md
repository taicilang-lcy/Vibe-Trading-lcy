# Clash 代理与数据源兼容性测试报告

> 测试日期：2026-06-11
> 测试环境：MacBook Pro M5 + 华硕路由器 Merlin Clash (TUN + Fake-IP 模式)

## 1. 背景

vibe-trading 项目的 Agent ad-hoc 模式需要同时访问国内数据源（tushare、akshare）和海外数据源（yfinance、okx）。使用路由器级 Clash 梯子时，部分数据源 API 调用失败，影响 Agent 正常工作。

## 2. 数据源网络需求

| 数据源 | 服务器位置 | 需要梯子 | Python 库 |
|--------|-----------|----------|-----------|
| tushare | 国内（api.tushare.pro） | ❌ 不需要 | `tushare` |
| akshare | 国内（东方财富 eastmoney.com） | ❌ 不需要 | `akshare` |
| yfinance | 海外（Yahoo Finance） | ✅ 需要 | `yfinance` |
| okx | 海外（okx.com） | ✅ 需要 | `ccxt` |

**矛盾：** 开梯子 → 国内源可能挂；关梯子 → 海外源一定挂。

## 3. 测试矩阵

### 3.1 路由器 Clash TUN + Fake-IP 模式（默认配置）

| 数据源 | Python 脚本测试 | Agent 实际使用 | curl 测试 |
|--------|----------------|---------------|-----------|
| tushare | ✅ 成功（5511 rows） | ❌ 失败（27 步才完成） | ✅ 成功 |
| akshare | ❌ RemoteDisconnected | ❌ 失败 | ✅ 成功 |
| yfinance | ✅ 成功 | ✅ 成功 | ✅ 成功 |

**关键发现：**
- curl 和 Python `requests` 表现不一致（同一 URL，curl 成功，Python 失败）
- DNS 返回 `198.18.0.x`（Clash fake-ip 地址）
- Python 脚本测试 tushare 成功，但 Agent 实际运行时失败（可能与时序、连接复用有关）

### 3.2 关闭梯子（无代理）

| 数据源 | Python 脚本测试 | Agent 实际使用 |
|--------|----------------|---------------|
| tushare | ✅ 成功 | ✅ 成功（2 步完成） |
| akshare | ✅ 成功 | ✅ 成功 |
| yfinance | ❌ 失败（Yahoo 不可达） | ❌ 失败 |

### 3.3 添加 Clash 分流规则后

添加的自定规则：

```yaml
# 国内数据源 — 直连
DOMAIN-SUFFIX,tushare.pro,DIRECT
DOMAIN-KEYWORD,push2,DIRECT
DOMAIN-SUFFIX,eastmoney.com,DIRECT

# 海外数据源 — 走代理
DOMAIN-SUFFIX,yahoo.com,Proxy
DOMAIN-SUFFIX,yahoo.co.jp,Proxy
DOMAIN-SUFFIX,okx.com,Proxy
```

**结果：** 分流规则生效（DNS 解析到 fake-ip，curl 测试通过），但 Python `requests` 仍然 RemoteDisconnected。

### 3.4 添加 fake-ip-filter 后

在 Clash DNS 配置中添加：

```yaml
fake-ip-filter:
  - '+.eastmoney.com'
  - '+.push2.eastmoney.com'
  - '+.push2his.eastmoney.com'
  - '+.tushare.pro'
  - '+.sina.com.cn'
```

**结果：DNS 返回真实 IP（不再是 198.18.0.x），但 tushare 也开始失败，情况更糟。已回滚。**

## 4. 根因分析

### 4.1 问题本质

```
Python requests 发起 HTTPS 请求
    ↓
路由器 Clash TUN 透明拦截（网络层，无法绕过）
    ↓
Clash 进行流量转发（无论 DIRECT 还是 Proxy）
    ↓
Python requests 的 TLS 握手被中断 → RemoteDisconnected
```

这不是 DNS 问题（fake-ip vs real-ip 都不行），不是分流规则问题（DIRECT 不行），而是 **Clash TUN 透明代理对 Python `requests`/`urllib3` 的 TLS 行为不兼容**。

### 4.2 为什么 curl 能成功但 Python 不行

| 维度 | curl | Python requests |
|------|------|----------------|
| TLS 实现 | macOS Security.framework | Python ssl 模块（OpenSSL） |
| HTTP/2 | 支持但默认 HTTP/1.1 | 取决于 urllib3 版本 |
| 连接管理 | 简单，每次新建 | 连接池复用（keep-alive） |
| 与 TUN 的兼容性 | ✅ 正常 | ❌ 被中断 |

### 4.3 Python 脚本测试 vs Agent 实际运行的差异

| 维度 | Python 脚本 | Agent（web server） |
|------|------------|-------------------|
| 运行环境 | 直接终端 | uvicorn/FastAPI 子进程 |
| 网络栈 | 干净 | 可能有连接池复用 |
| 时序 | 单次请求 | 多轮 ReAct，频繁请求 |
| 稳定性 | 偶尔成功 | 经常失败 |

## 5. 已验证的结论

| 结论 | 依据 |
|------|------|
| 路由器级 Clash TUN 与 Python `requests` 不兼容 | curl 成功但 Python 失败（同 URL） |
| 分流规则（DIRECT）不能解决 Python 兼容性问题 | 规则生效但 Python 仍失败 |
| fake-ip-filter 不能解决问题 | 改为真实 IP 后 Python 仍然失败 |
| 关梯子后所有国内源正常 | tushare + akshare 均正常，Agent 2 步完成 |
| yfinance 需要梯子 | Yahoo Finance 国内不可达 |

## 6. 可行方案

### 方案 A：Mac 本地 Clash 客户端（推荐）

- 路由器关闭 Clash，改为 Mac 上运行 ClashX / Mihomo
- 使用**系统代理模式**（非 TUN 模式）
- Python `requests` 完全兼容系统代理
- 分流规则可以精确控制哪些域名走代理

**优点：** Python 兼容、精确控制、国内源直连无问题
**缺点：** 需要在 Mac 上额外运行 Clash 客户端

### 方案 B：路由器 Clash 切到 Redir-Host 模式

- 在 Clash DNS 设置里选「默认:Redir-Host」代替 Fake-IP
- 不使用 fake-ip，DNS 返回真实 IP
- 可能改善 Python 兼容性（未测试）

**优点：** 不需要额外客户端
**缺点：** 可能被 DNS 污染；兼容性不确定

### 方案 C：按需开关梯子

- 使用国内数据源时关梯子
- 需要海外数据时开梯子
- `check_data_source` 工具已能正确路由，但无法解决网络层问题

**优点：** 最简单
**缺点：** 手动操作，无法同时访问国内外源

### 方案 D：项目中优雅降级

- Agent 检测到数据源失败时自动降级
- `check_data_source` 工具已实现优先级链和 fallback
- 开梯子时 tushare 失败 → 自动尝试 akshare → 再失败则用 Extensions API

**优点：** 不需要改网络配置
**缺点：** 降级可能丢失数据质量

## 7. 对 check_data_source 工具的影响

`check_data_source` 工具的数据源优先级逻辑不受 Clash 影响——它只返回推荐的数据源顺序。但实际数据获取是否成功取决于网络环境：

| 环境 | tushare | akshare | yfinance | Agent 可用性 |
|------|---------|---------|----------|-------------|
| 无梯子 | ✅ | ✅ | ❌ | A 股分析完全可用 |
| 路由器 TUN 梯子 | ⚠️ 不稳定 | ❌ | ✅ | 不可靠 |
| Mac 系统代理梯子 | ✅ 预期可用 | ✅ 预期可用 | ✅ | ✅ 预期完全可用 |

## 8. 后续行动

| 优先级 | 行动 | 状态 |
|--------|------|------|
| ✅ 已完成 | `check_data_source` 工具实现 | 已通过 32 个测试 |
| ✅ 已完成 | `data-routing` SKILL.md 更新 | 已引导 Agent 调用工具 |
| ✅ 已完成 | Agent ad-hoc 验证（无梯子） | 2 步完成，tushare 优先 ✅ |
| 🔲 待做 | 验证 Mac 本地 Clash 系统代理模式 | 需要安装 ClashX/Mihomo |
| 🔲 待做 | 测试路由器 Redir-Host 模式 | 需要切换 DNS 方案 |
| 🔲 待做 | 实现 Agent 级别的数据源降级 | `check_data_source` 已支持 fallback chain |

## 9. 测试命令参考

```bash
# 测试 tushare
source .venv/bin/activate
python3 -c "
import tushare as ts, os
from dotenv import load_dotenv; load_dotenv('agent/.env')
pro = ts.pro_api(os.getenv('TUSHARE_TOKEN'))
print(f'tushare: {len(pro.daily(trade_date=\"20260611\"))} rows')
"

# 测试 akshare
python3 -c "
import akshare as ak
print(f'akshare: {len(ak.stock_zh_a_spot_em())} rows')
"

# 测试 yfinance
python3 -c "
import yfinance as yf
print(f'yfinance: {len(yf.Ticker(\"AAPL\").history(period=\"5d\"))} rows')
"

# 检查 DNS 解析
python3 -c "
import socket
for d in ['api.tushare.pro', '82.push2.eastmoney.com', 'yahoo.com']:
    print(f'{d} -> {socket.gethostbyname(d)}')
"

# curl 对比测试
curl -s -o /dev/null -w '%{http_code} %{remote_ip} %{time_total}s\n' \
  'https://api.tushare.pro' --connect-timeout 5
curl -s -o /dev/null -w '%{http_code} %{remote_ip} %{time_total}s\n' \
  'https://82.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=1&fs=m:0+t:6&fields=f12' --connect-timeout 5
```

## 10. 相关文件

| 文件 | 说明 |
|------|------|
| `agent/src/tools/check_data_source_tool.py` | 数据源优先级检查工具 |
| `agent/tests/test_check_data_source_tool.py` | 工具测试（32 个） |
| `agent/src/skills/data-routing/SKILL.md` | 数据路由技能文档 |
| `agent/backtest/loaders/registry.py` | FALLBACK_CHAINS 定义 |
| `extensions/core/dispatcher.py` | Extensions 数据调度器 |
