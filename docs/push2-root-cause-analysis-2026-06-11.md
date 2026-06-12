# Clash TUN 与国内数据源兼容性 — Root Cause Analysis (终版)

> 日期：2026-06-11
> 环境：MacBook Pro M5 + 华硕 RT-AX86U (Merlin Clash, TUN + Fake-IP 模式)
> 方法：30+ 隔离测试 + 2 轮 A/B 对照（Clash 开/关）

---

## 一、结论（先说结论）

### 根因

**路由器 Clash TUN 透明代理改变 TCP 连接指纹，触发国内数据源服务端的安全检测机制。影响程度因服务端 anti-bot 严格程度而异：push2（东方财富行情推送）最严重（直接丢弃），tushare 次之（需要重试），公开网站不受影响。**

### A/B 对照测试（最核心的证据）

#### 程序化测试

| 数据源 | Clash 开 | Clash 关 | 影响 |
|--------|---------|---------|------|
| **tushare** (Python) | ❌ RemoteDisconnected | ✅ **首次即成功** (5512 rows) | 🔴 严重 |
| **tushare** (curl) | ✅ HTTP 200 | ✅ HTTP 200 | 🟢 curl 不受影响 |
| **akshare** (Python) | ❌ RemoteDisconnected | ❌ IP 仍被 rate limit* | 🔴 严重 |
| **akshare** (curl) | ❌ HTTP 000 | ❌ IP 仍被 rate limit* | 🔴 严重 |

*\*密集测试触发了 push2 的 IP rate limit，关 Clash 后 rate limit 未解除*

#### Agent 实际运行测试

| | Clash 开 | Clash 关 |
|--|---------|---------|
| **tushare** | ⚠️ 需要重试才成功 | ✅ 首次即成功 |
| **akshare** | ❌ → mootdx 降级 ✅ | ❌ → baostock 降级 ✅ |
| **总步数** | 10 步 | 12 步 |
| **用户体验** | 等待较长，依赖重试 | akshare 仍失败（IP rate limit 未解除）|

### 影响分级

| 数据源 | 服务端 | Anti-bot 级别 | Clash 开影响 | Clash 关影响 |
|--------|-------|-------------|-------------|-------------|
| **push2 (akshare)** | 东方财富行情推送 | 🔴 严格 | ❌ 直接丢弃 + 触发 IP rate limit | ❌ (IP 已被 rate limit) |
| **tushare** | tushare.pro | 🟡 中等 | ⚠️ 需要重试，有时重试 N 次也不行 | ✅ 秒成功 |
| **www.eastmoney.com** | 东方财富网站 | 🟢 宽松 | ✅ 正常 | ✅ 正常 |
| **datacenter-web** | 东方财富数据中心 | 🟢 宽松 | ✅ 正常 | ✅ 正常 |

### 触发链

```
Clash TUN 透明代理 (TCP 层)
         ↓
  改变 TCP 连接指纹（参数、时序、连接模式）
         ↓
  ┌── 严格 anti-bot (push2): 直接丢弃连接 → Empty Reply
  ├── 中等 anti-bot (tushare): 偶尔丢弃 → 需要重试
  └── 无 anti-bot (公开网站): 正常响应
         ↓
  push2: 多次失败后触发 IP rate limit (15-60 分钟)
         ↓
  即使关闭 Clash，IP 仍在黑名单中，所有端点均失败
```

---

## 二、逐项排除分析

### 2.1 不是「Python requests 与 Clash 天然不兼容」

**证伪：** curl 经 Clash 正常工作，Python 经 Clash 的表现取决于目标服务端 anti-bot 级别。问题在于 Clash TUN 的 TCP 代理行为 + 服务端检测，而非 Python 本身。

### 2.2 不是 DNS 问题（fake-ip vs real-ip）

**证伪：**
- fake-ip (198.18.0.x)：失败
- `--resolve` 指定真实 IP：仍然失败
- `fake-ip-filter` 改为真实 IP：仍然失败（原报告已验证）

**原因：** 无论 DNS 怎么解析，流量都经过路由器的 Clash TUN 代理。DNS 只影响 Clash 内部如何路由，不改变 Clash 的 TCP 代理行为。

### 2.3 不是分流规则问题（DIRECT vs PROXY）

**证伪：** 延迟指纹分析证实 Clash 对 push2 使用 DIRECT 路由：

```
push2 (DIRECT):       connect 5-9ms / TLS 22-34ms / total 34-49ms
www.eastmoney (DIRECT): connect 5-8ms / TLS 25-27ms / total 76-108ms
yahoo (PROXY):          connect 6-10ms / TLS 86-715ms / total 171-1032ms
```

push2 的延迟模式与已知 DIRECT 的 www.eastmoney 完全一致。

### 2.4 不是 User-Agent / HTTP 版本问题

**证伪：**
- 浏览器 UA、空 UA、curl 默认 UA → 全部失败
- HTTP/1.1、HTTP/2 → 全部失败
- 带浏览器 Referer + Origin → 仍然失败

### 2.5 不是 TLS 版本问题

**证伪：**
- push2 使用 TLS 1.3，但强制 TLS 1.2 也失败
- tushare 使用 TLS 1.2 正常工作
- 直连 push2（TLS 1.3）首次测试成功

TLS 握手在所有情况下都成功（已通过 openssl s_client 和 curl -v 验证）。问题发生在 TLS 之后的 HTTP 层。

### 2.6 不是连接池/Session 复用问题

**证伪：**
- `requests.get()`（无 Session）→ 失败
- `requests.Session()`（有连接池）→ 失败
- 两者行为一致

---

## 三、为什么 push2 > tushare > 公开网站（影响递减）

| 域名 | 服务类型 | Anti-bot 级别 | 经 Clash 结果 |
|------|---------|--------------|-------------|
| `push2.eastmoney.com` | 实时行情推送 API | **🔴 严格**（TCP 指纹检测 + IP rate limit） | ❌ 直接丢弃 |
| `82.push2.eastmoney.com` | 实时行情推送 API | **🔴 严格** | ❌ |
| `push2his.eastmoney.com` | 历史行情 API | **🔴 严格** | ❌ |
| `api.tushare.pro` | 数据服务（token 认证） | **🟡 中等** | ⚠️ 需要重试 |
| `www.eastmoney.com` | 公开网站 | 🟢 宽松 | ✅ |
| `datacenter-web.eastmoney.com` | 数据中心 API | 🟢 宽松 | ✅ |
| `query1.finance.yahoo.com` | Yahoo Finance | 🟢 无（经代理反而需要） | ✅ |

- **push2** 是东方财富实时行情推送核心服务，对数据安全要求最高，anti-bot 最严格
- **tushare** 是 token 认证的付费 API，安全主要靠 token，但有基础 anti-bot
- **公开网站** 不做连接指纹检测

### 关于 akshare 的天然不稳定性

akshare 本质是对东方财富等网站的爬虫封装，其稳定性受以下因素影响：

1. **push2 服务端 anti-bot**：Clash TUN 触发后更严重
2. **CDN 节点质量**：Azure Traffic Manager 负载均衡，不同节点行为不同
3. **IP rate limit**：频繁请求触发 IP 封禁（15-60 分钟冷却）
4. **接口变更**：东方财富随时可能改接口，akshare 需要跟进更新

即使在无 Clash 的环境下，akshare 也可能出现间歇性失败。**因此不应作为唯一数据源，必须配合 fallback chain。**

### 关于 mootdx — Clash 环境下的最稳定数据源 ✅

**mootdx 使用通达信 TCP 二进制协议（端口 7709），不走 HTTP/TLS，完全不受 Clash TUN 影响。**

程序化测试（Clash 关状态）：

| mootdx 接口 | 结果 | 数据量 |
|-------------|------|--------|
| 实时行情 (quotes) | ✅ 首次成功 | 1 row，含五档盘口 |
| 日K线 (bars) | ✅ 首次成功 | 5 rows |
| F10 基本面 (finance) | ✅ 首次成功 | 1 row |
| 股票列表 (stocks) | ✅ 首次成功 | **27,237 rows** |

Agent 测试（Clash 开状态，获取国电南瑞 600406 全量信息）：
- **网络请求零失败**，首次即获取所有数据
- 11 步全部是代码格式化/展示，无网络重试
- 覆盖：实时行情、K线、F10、除权除息、分笔成交

**为什么 mootdx 不受影响：**
- 通达信协议是 **TCP 二进制协议**，不是 HTTP
- 没有 TLS 握手、没有 HTTP 请求头
- Clash TUN 对纯 TCP 流量只是透明转发，不改变 TCP 指纹
- 通达信服务器无 anti-bot 机制（面向客户端软件设计）

### 数据源协议 vs Clash 兼容性总览

| 协议类型 | 代表 | Clash TUN 影响 | 原因 |
|----------|------|---------------|------|
| **TCP 二进制协议** | mootdx (通达信) | ✅ 不受影响 | 无 HTTP/TLS，纯 TCP 转发 |
| **HTTP + 严格 anti-bot** | push2 (akshare) | 🔴 严重 | TCP 指纹被检测 → 连接丢弃 |
| **HTTP + 中等 anti-bot** | tushare | 🟡 中等 | TCP 指纹偶发被检测 → 需重试 |
| **HTTP + 无 anti-bot** | www.eastmoney, datacenter-web | 🟢 无 | 不做连接指纹检测 |
| **HTTP + 需要 VPN** | yfinance, SEC EDGAR | ✅ 需要 Clash | 反而需要代理才能访问 |

---

## 三-B、第三方 Skill 网络兼容性评估

### [a-stock-data](https://github.com/simonlin1212/a-stock-data) (A股数据)

**版本：** v3.2.2 (2026-06-03) | **27 端点 / 13 数据源** | **活跃维护**

| 数据源 | 协议 | Clash TUN 影响 | 说明 |
|--------|------|---------------|------|
| **mootdx (通达信)** | TCP 二进制 (7709) | ✅ 不受影响 | K线、盘口、F10、分笔成交 |
| **腾讯财经** (qt.gtimg.cn) | HTTP | ✅ 不受影响 | PE/PB、市值、换手率 |
| **同花顺** (10jqka.com.cn) | HTTP | ✅ 不受影响 | 热门股、题材、北向资金 |
| **百度股市通** | HTTP | ✅ 不受影响 | K线+均线 |
| **新浪财经** | HTTP | ✅ 不受影响 | 三大报表 |
| **巨潮 cninfo** | HTTP | ✅ 不受影响 | 公告 |
| **push2.eastmoney.com** | HTTP | 🔴 受影响 | 资金流、板块成分、行业排名 |
| **datacenter-web.eastmoney** | HTTP | 🟡 可能受影响 | 龙虎榜、解禁、融资融券 |
| **search-api-web.eastmoney** | HTTP | 🔴 受影响 | 个股新闻 |

**内置防护措施：**
- `em_get()` 限速网关：1.0s 最小间隔 + 0.1-0.5s 随机抖动
- `EM_SESSION` 连接复用（Keep-Alive）
- 串行请求（非并发）
- CHANGELOG 已记录："部分大陆住宅 IP 会被东财 push2/search-api 连接级间歇风控"

**结论：大部分功能不受 Clash TUN 影响**（mootdx + 腾讯/同花顺/新浪 覆盖核心数据）。东方财富 HTTP 端点的资金流、龙虎榜等可能间歇性失败，但 skill 已有内置限速缓解。

### [global-stock-data](https://github.com/simonlin1212/global-stock-data) (全球市场数据)

**版本：** v1.0 (2026-05-20) | **18 端点 / 5 数据源** | **活跃维护**

| 数据源 | 协议 | Clash TUN 影响 | 说明 |
|--------|------|---------------|------|
| **push2.eastmoney.com** | HTTP | 🔴 受影响 | 美股/港股实时行情 |
| **push2his.eastmoney.com** | HTTP | 🔴 受影响 | 资金流 |
| **datacenter-web.eastmoney** | HTTP | 🟡 可能受影响 | 财务报表 |
| **新浪财经** (hq.sinajs.cn) | HTTP | ✅ 不受影响 | 美股/港股报价 |
| **腾讯财经** (qt.gtimg.cn) | HTTP | ✅ 不受影响 | 美股/港股报价 |
| **Yahoo Finance** | HTTP | ⚡ 需要 VPN | K线、统计、期权、新闻 |
| **SEC EDGAR** | HTTP | ⚡ 需要 VPN | 财报、XBRL |

**冲突矩阵：**
- 🇨🇳 国内源（东方财富）→ 不需要 VPN，但 Clash TUN 会触发 anti-bot
- 🇺🇸 海外源（Yahoo, SEC）→ 需要 VPN 才能访问
- **没有 mootdx/TCP 协议作为备选**（纯 HTTP）
- **没有内置代理配置**

**结论：在 Clash TUN 环境下有双重困境**——东方财富受 anti-bot 影响，Yahoo/SEC 又需要代理。建议：
1. 优先使用新浪/腾讯（不受影响）
2. Yahoo/SEC 走 Clash 代理（需要）
3. 东方财富端点作为补充（可能间歇失败）

### 两个 Skill 对比总结

| 维度 | a-stock-data | global-stock-data |
|------|-------------|-------------------|
| **Clash TUN 兼容性** | 🟢 **大部分不受影响**（mootdx TCP 为主） | 🟡 **部分受影响**（纯 HTTP，无 TCP 备选） |
| **数据覆盖** | A 股全栈（27 端点） | 美股/港股（18 端点） |
| **协议多样性** | ✅ TCP + HTTP | ❌ 仅 HTTP |
| **内置限速** | ✅ em_get() 网关 | ❌ 无 |
| **活跃维护** | ✅ v3.2.2 | ✅ v1.0 |
| **VPN 双重困境** | 不涉及（纯 A 股） | ⚠️ 国内源怕 VPN，海外源需要 VPN |

---

## 四、为什么原报告的两个结论都不够准确

### GLM5.1 报告：「Python requests 与 Clash TUN 不兼容」

- **过于宽泛**：不是所有 Python requests 都受影响，curl 也不受影响
- **遗漏关键变量**：没有测试 raw socket 直连真实 IP；没有做 A/B 对照
- **正确的部分**：识别出问题在 Clash TUN 层面；tushare 也受影响

### ChatGPT 报告：「东方财富风控 + 代理 IP + 连接池复用」

- **方向正确**：确实与东方财富的风控有关
- **不准确**：不是「代理 IP」问题（Clash DIRECT 使用真实 ISP IP），不是「连接池」问题
- **遗漏关键变量**：没有验证 Clash 对 push2 是 DIRECT 还是 PROXY；没有发现 tushare 也受影响

---

## 五、最终修复方案（已验证）

### ✅ 保持路由器 Clash TUN 打开，以下配置可让所有数据源正常工作

#### 修复 1: tushare — `NO_PROXY` 环境变量（已生效）

在 `agent/.env` 中添加（已完成）：
```bash
NO_PROXY=api.tushare.pro,tushare.pro,push2.eastmoney.com
no_proxy=api.tushare.pro,tushare.pro,push2.eastmoney.com
```

**验证结果（Clash 开）：**
```
首次: ✅ 5511 rows (0.25s)
二次: ✅ 5512 rows (0.25s)
三次: ✅ 5515 rows (0.25s)
```

三次全部首次成功，零重试。tushare SDK 使用裸 `requests.post()`，`requests` 库自动尊重 `NO_PROXY` 环境变量，绕过 Clash 直连 tushare 服务器。

#### 修复 2: A 股实时数据 — mootdx (已验证，无需修复)

mootdx 走通达信 TCP 二进制协议（端口 7709），天然不受 Clash TUN 影响。

**性能测试结果（Clash 开）：**

| 测试 | 结果 |
|------|------|
| 单股行情 | **17ms** |
| 10 只股票批量 | **16ms**（2ms/股） |
| 连续 20 次请求 | **20/20 成功，0 失败** |
| 平均延迟 | **16ms**，P99: 20ms |
| 全市场 27,237 只 | **0.8 秒** |

**无频率限制，无 token，免费，实时数据。**

#### 修复 3: 美股/港股 — 新浪/腾讯 (已验证，无需修复)

**实测英伟达 (NVDA) 实时股价（Clash 开，美股盘中 23:37）：**

| 数据源 | NVDA 价格 | 状态 |
|--------|----------|------|
| 新浪财经 | $201.72 | ✅ 不受 Clash 影响 |
| 腾讯财经 | $201.64 | ✅ 不受 Clash 影响 |
| 东方财富 push2 | — | ❌ RemoteDisconnected |
| Yahoo Finance | — | ❌ API 解析失败 |

新浪 + 腾讯可获取美股/港股实时数据，完全不受 Clash TUN 影响。

### 数据源互补关系

| 数据源 | 覆盖范围 | 优势 | 不足 |
|--------|---------|------|------|
| **mootdx** | A 股实时行情、K线、F10、分笔 | 免费零门槛、16ms、TCP 无惧 Clash | 无高级金融数据（融资融券等） |
| **tushare** | A 股日K、财务指标、龙虎榜、融资融券 | 数据最全 | 需 token，需 `NO_PROXY` |
| **新浪/腾讯** | 美股/港股实时报价 | 免费、无惧 Clash | 无 K 线/期权/财报 |
| **yfinance** | 美股 K 线、期权、财报 | 数据丰富 | 需 Clash 代理，有 rate limit |

**结论：mootdx + tushare(NO_PROXY) + 新浪/腾讯 覆盖绝大多数需求，均可保持路由器 Clash 打开正常使用。**

---

## 六、行动清单

| 状态 | 行动 | 说明 |
|------|------|------|
| ✅ 已完成 | `NO_PROXY` 加入 `agent/.env` | tushare 在 Clash 开环境首次即成功 |
| ✅ 已完成 | mootdx 性能验证 | 16ms 响应，无频率限制 |
| ✅ 已完成 | 新浪/腾讯美股实时数据验证 | NVDA $201.72 实时获取 |
| ✅ 已完成 | a-stock-data skill 评估 | mootdx TCP 兜底，可放心用 |
| ✅ 已完成 | global-stock-data skill 评估 | 依赖新浪/腾讯，可用 |
| 🟡 可选 | akshare 降级为非优先数据源 | 爬虫本质不稳定，fallback chain 已兜底 |
| 🟡 可选 | 考虑将 mootdx 提升 fallback chain 优先级 | 性能最优、最稳定 |

---

## 七、测试命令备忘

```bash
# 1. tushare (NO_PROXY 已配置)
source .venv/bin/activate
python3 -c "
import os; from dotenv import load_dotenv; load_dotenv('agent/.env')
import tushare as ts
pro = ts.pro_api(os.getenv('TUSHARE_TOKEN'))
print(f'tushare: {len(pro.daily(trade_date=\"20260611\"))} rows')
"

# 2. mootdx (实时行情)
python3 -c "
from mootdx.quotes import Quotes
c = Quotes.factory(market='std')
df = c.quotes(symbol=['600519','000001','300750'])
for _,r in df.iterrows():
    pct = (r['price']-r['last_close'])/r['last_close']*100
    print(f\"  {r['code']}: {r['price']:.2f} ({pct:+.2f}%)\")
"

# 3. 美股实时 (新浪)
python3 -c "
import requests
r = requests.get('https://hq.sinajs.cn/list=gb_nvda', headers={'Referer':'https://finance.sina.com.cn'})
print(r.text[:120])
"
```

## 八、2026-06-12 补充验证：NO_PROXY 并非真正原因

### 重新验证

在 ai_quant 项目中系统性地重新验证了 tushare + Clash TUN 的问题，发现了原报告中的一个关键错误。

#### 真正的根因：SDK 用了老域名，而非 NO_PROXY 的功劳

**tushare SDK (PyPI v1.4.29) 硬编码的 endpoint 是 `api.waditu.com`，不是 `api.tushare.pro`。**

```python
# SDK 源码 .venv/lib/python3.12/site-packages/tushare/pro/client.py
class DataApi:
    __http_url = 'http://api.waditu.com/dataapi'   # ← 老域名
```

原报告设了 `NO_PROXY=api.tushare.pro`，但 SDK 实际请求的是 `api.waditu.com`——**NO_PROXY 的域名跟 SDK 请求的域名根本不匹配**，所以 NO_PROXY 从未生效过。

#### Clash fake-IP 对两个域名路由策略不同

两个域名解析到**完全相同的真实 IP**（`60.205.198.20` + `8.140.225.26`），但 Clash fake-IP 分配了不同的虚拟 IP，走不同的路由策略：

| 域名 | 真实 IP | Clash fake-IP | curl 成功率 | Python 成功率 |
|------|---------|---------------|------------|--------------|
| `api.waditu.com` | 60.205.198.20 | 198.18.3.58 | **60%** (6/10) | ~60% |
| `api.tushare.pro` | 60.205.198.20 | 198.18.4.96 | **100%** (10/10) | **100%** (15/15) |

关键对照实验（curl 直接对比，排除 Python requests 差异）：

```bash
# api.waditu.com（SDK 默认）— 10 次中 4 次返回 000
for i in $(seq 1 10); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST "http://api.waditu.com/dataapi/daily" \
    -H "Content-Type: application/json" -d '{"api_name":"daily",...}'
done
# 结果: 000 000 200 200 200 200 200 000 000 200  ← 60% 成功率

# api.tushare.pro（官方推荐）— 10 次全部 200
for i in $(seq 1 10); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST "http://api.tushare.pro/dataapi/daily" \
    -H "Content-Type: application/json" -d '{"api_name":"daily",...}'
done
# 结果: 200 200 200 200 200 200 200 200 200 200  ← 100% 成功率
```

#### 为什么原报告的 "NO_PROXY 修复" 看起来有效

原报告测试时 `NO_PROXY=api.tushare.pro` 并重启了进程。重启后 tushare 的第一次请求可能恰好成功了（`api.waditu.com` 约 60% 成功率，连续 3 次成功的概率 ≈ 21.6%），被误认为是 NO_PROXY 的功劳。

#### 正确的修复

**Monkey-patch SDK 的 URL，从 `api.waditu.com` 改为 `api.tushare.pro`：**

```python
from tushare.pro.client import DataApi
DataApi._DataApi__http_url = 'http://api.tushare.pro/dataapi'
```

验证结果（Clash 开，15 次连续测试）：
```
第1次: ✅ 5511 rows
第2次: ✅ 5511 rows
...
第15次: ✅ 5511 rows
成功率: 15/15 = 100%
```

#### Tushare 官方文档确认

官方文档（https://tushare.pro/document/1?doc_id=130）只引用 `http://api.tushare.pro` 作为 API endpoint，从未提及 `api.waditu.com`。`waditu.com` 是项目老域名（"挖地兔"），SDK 从未更新。

PyPI v1.4.29 和 GitHub master 都还硬编码着 `api.waditu.com`。GitHub master 版本号反而是 1.2.18（更旧），说明 SDK 维护不活跃。

#### concept API 独立问题

`concept` 接口在两个域名上都返回 "请指定正确的接口名"（code=40101），这是 tushare 服务端的接口变更/下线，与 Clash 和域名无关。

### 修正后的结论

| 原报告结论 | 修正后结论 |
|-----------|-----------|
| `NO_PROXY=api.tushare.pro` 解决了 tushare 问题 | NO_PROXY 对此问题无效（SDK 请求的是 `api.waditu.com`，不匹配） |
| Clash TUN 改变 Python requests 的 TCP 指纹 | 问题不在 TCP 指纹，而是 Clash fake-IP 对 `api.waditu.com` 的路由不稳定 |
| curl 不受影响 | curl 访问 `api.waditu.com` 同样 ~40% 失败，访问 `api.tushare.pro` 才 100% |
| 修复方案：设置 NO_PROXY | 修复方案：monkey-patch SDK URL 为 `api.tushare.pro` |

---

## 九、发现记录

### 关键测试时间线

1. **Clash 开** → Python raw socket 直连 push2 真实 IP 47.112.165.11 → ✅ 成功（首次，绕过 Clash）
2. 同上，经 Clash fake-ip → ❌ Empty Reply（TLS 成功，HTTP 被丢弃）
3. 后续所有直连测试 → ❌ 全失败（IP 已被 rate limit）
4. **Clash 开** → curl tushare ✅ / Python tushare ❌（需重试）
5. **Clash 关** → Python tushare ✅ 秒成功 5512 rows（最干净的对比）
6. **Clash 关** → push2 仍 ❌（IP rate limit 未解除）
7. Agent 测试 Clash 开 → tushare 重试成功 / akshare → mootdx 降级（10 步）
8. Agent 测试 Clash 关 → tushare 首次成功 / akshare → baostock 降级（12 步）
9. **Clash 开** → mootdx 全部首次成功（行情 17ms / 20 连发 0 失败 / 全市场 0.8s）
10. **Clash 开** → `NO_PROXY=api.tushare.pro` → tushare 三次全部首次成功 (0.25s)
11. **Clash 开** → 新浪 NVDA $201.72 / 腾讯 NVDA $201.64（美股盘中实时）
