# 加密货币数据收集系统

本目录提供了多种加密货币数据收集解决方案，支持完整的OHLC数据获取和策略回测功能。

## 🎯 推荐方案

| 数据源 | 成本 | OHLC支持 | 推荐程度 | 文档 | OKX集成 |
|--------|------|----------|----------|------|---------|
| **OKX集成方案** | 免费 | ✅ 完整 | ⭐⭐⭐⭐⭐⭐ | 本文档 | ✅ 原生支持 |
| **Binance API** | 免费 | ✅ 完整 | ⭐⭐⭐⭐⭐ | [README_Binance.md](./README_Binance.md) | 🔧 需配置 |
| TradingView | $14.95/月 | ✅ 完整 | ⭐⭐⭐ | [README_TradingView.md](./README_TradingView.md) | ❌ 无集成 |
| CoinGecko | 免费 | ❌ 仅价格 | ⭐⭐ | 本文档 | ❌ 无集成 |

**🚀 最新推荐**: 使用 **OKX集成方案**，它提供完整的端到端解决方案，包括自动配置获取、符号映射、数据收集和实时交易集成。

**📦 v3.2版本更新**: 新增智能订单管理和防重复交易系统，提供生产级稳定性保障。

## 🏗️ 系统架构概览

### 完整解决方案对比

| 功能模块 | OKX集成方案 | Binance方案 | TradingView方案 | CoinGecko方案 |
|----------|-------------|------------|----------------|---------------|
| **数据收集器** | `okx_integration_starter.py` + `binance_collector.py` | `binance_collector.py` | `tradingview_collector.py` | `collector.py` |
| **数据转换器** | 自动化 + `binance_dump_bin.py` | `binance_dump_bin.py` | `tradingview_dump_bin.py` | `dump_bin.py` |
| **配置管理** | `okx_config_client.py` (自动获取) | 手动配置 | 手动配置 | 手动配置 |
| **符号映射** | ✅ 自动映射 | ❌ 手动处理 | ❌ 手动处理 | ❌ 无 |
| **系统启动器** | `okx_integration_starter.py` | `binance_analyzer_starter.py` | `start_crypto_analyzer.py` | 无 |
| **Go客户端** | 原生集成 | 需要适配 | 生成代码 | 无 |
| **一键部署** | ✅ 支持 | ❌ 手动 | ❌ 手动 | ❌ 手动 |
| **OHLC支持** | ✅ 完整 | ✅ 完整 | ✅ 完整 | ❌ 仅价格 |
| **回测能力** | ✅ 支持 | ✅ 支持 | ✅ 支持 | ❌ 不支持 |
| **成本** | 免费 | 免费 | $14.95/月 | 免费 |

### 核心架构组件

```
加密货币交易分析系统
├── 📊 数据收集层
│   ├── Binance API (推荐) - 完整OHLC，免费
│   ├── TradingView API - 多交易所聚合，付费
│   └── CoinGecko API - 仅价格数据，免费
├── 🔄 数据处理层
│   ├── 数据收集器 (Collector)
│   ├── 数据标准化 (Normalize) 
│   └── qlib格式转换 (DumpBin)
├── 🧠 分析决策层
│   ├── 实时分析器 (crypto_realtime_analyzer.py)
│   ├── 技术指标计算 (RSI, MACD, 布林带等)
│   ├── 机器学习预测 (qlib ML模型)
│   └── 交易信号生成
├── 🔗 通信接口层
│   ├── HTTP RESTful API
│   ├── WebSocket实时通信
│   ├── Redis消息队列
│   └── 文件输出 (JSON/CSV)
└── 🤖 Go客户端层
    ├── 信号接收和解析
    ├── 多因子信号验证
    ├── 风险管理 (止损止盈)
    └── 交易执行决策
```

### 数据流向图

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│ 交易所API   │───▶│ 数据收集器    │───▶│ CSV原始数据  │
└─────────────┘    └──────────────┘    └─────────────┘
                            │                    │
                            ▼                    ▼
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│ Go交易程序  │◀───│ 通信接口层    │◀───│ qlib二进制   │
└─────────────┘    └──────────────┘    └─────────────┘
       │                    ▲                    ▲
       │                    │                    │
       ▼            ┌──────────────┐    ┌─────────────┐
┌─────────────┐    │ 实时分析器    │◀───│ 数据转换器   │
│ 交易决策    │    └──────────────┘    └─────────────┘
└─────────────┘           │
       ▲                  ▼
       │           ┌──────────────┐
       └───────────│ 交易信号生成  │
                   └──────────────┘
```

## 🚀 OKX集成方案（推荐）

### 特性概览

OKX集成方案是专为okx_strategy项目设计的完整解决方案，提供：

- **🔄 自动配置获取**: 从okx_strategy项目自动获取Binance和交易配置
- **🗺️ 智能符号映射**: 自动转换Binance符号到OKX格式（BTCUSDT → BTC-USDT-SWAP）
- **📊 完整数据链路**: Binance数据收集 → ML分析 → OKX交易执行
- **🛠️ 一键部署**: 单命令启动完整系统
- **⚡ 实时集成**: 与okx_strategy项目原生集成

### 快速开始

#### 1. 前提条件

确保okx_strategy项目已启动并提供配置API：

```bash
# 在okx_strategy项目目录
go run main.go
# 配置API现在运行在 http://localhost:9090
```

#### 2. 启动OKX集成分析器

```bash
cd /path/to/qlib/scripts/data_collector/crypto

# 完整系统：自动收集数据 + 启动分析
python okx_integration_starter.py full \
    --okx-api http://localhost:9090 \
    --start-date 2023-01-01

# 仅收集历史数据
python okx_integration_starter.py collect \
    --okx-api http://localhost:9090

# 仅启动分析（数据已准备）
python okx_integration_starter.py analyze \
    --okx-api http://localhost:9090
```

#### 3. 验证集成状态

```bash
# 检查配置获取
curl http://localhost:9090/api/v1/config/binance
curl http://localhost:9090/api/v1/config/symbol-mapping

# 检查qlib分析器
curl http://localhost:8080/health
curl http://localhost:8080/signals/latest
```

### 核心组件

#### OKX配置客户端 (`okx_config_client.py`)

自动从okx_strategy获取配置的Python客户端：

```python
from qlib.contrib.strategy.okx_config_client import create_okx_config_client

# 创建客户端
client = create_okx_config_client("http://localhost:9090")

# 获取推荐交易对
symbols = client.get_recommended_symbols()
# ['BTCUSDT', 'ETHUSDT', 'ADAUSDT', ...]

# 获取符号映射
mapping = client.get_symbol_mapping()
# {'BTCUSDT': 'BTC-USDT-SWAP', 'ETHUSDT': 'ETH-USDT-SWAP', ...}

# 转换符号格式
okx_symbols = client.convert_symbols_for_okx(symbols)
# ['BTC-USDT-SWAP', 'ETH-USDT-SWAP', ...]

# 检查集成状态
status = client.get_integration_status()
print(f"集成就绪: {status['integration_ready']}")
```

#### OKX集成启动器 (`okx_integration_starter.py`)

完整的集成启动系统：

```python
from okx_integration_starter import OKXIntegratedAnalysisSystem

# 创建系统实例
system = OKXIntegratedAnalysisSystem(
    okx_api_url="http://localhost:9090",
    data_dir="~/.qlib/okx_binance_data",
    qlib_data_dir="~/.qlib/qlib_data/okx_crypto",
    output_dir="/tmp/okx_crypto_signals",
)

# 检查集成状态
if system.check_integration_status():
    # 收集历史数据
    system.collect_historical_data(start_date="2023-01-01")
    
    # 启动分析系统
    system.start_analysis_system()
```

### 自动化功能

#### 1. 配置自动获取

系统启动时自动：
- 从okx_strategy获取Binance API配置
- 获取推荐的交易对列表
- 获取符号映射规则
- 获取数据收集参数

#### 2. 符号智能映射

自动处理不同交易所的符号格式：

| Binance格式 | OKX格式 | 自动转换 |
|-------------|---------|----------|
| BTCUSDT | BTC-USDT-SWAP | ✅ |
| ETHUSDT | ETH-USDT-SWAP | ✅ |
| BNBUSDT | BNB-USDT-SWAP | ✅ |

#### 3. 数据流优化

```
1. okx_strategy启动 → 配置API (9090)
2. qlib获取配置 → HTTP请求配置
3. 数据自动收集 → Binance API → 本地存储
4. 实时分析 → ML + 技术指标
5. 符号转换 → Binance → OKX格式
6. 信号传输 → okx_strategy接收
7. 交易执行 → 自动化交易
```

### 高级功能

#### 集成状态监控

```python
# 实时监控集成状态
status = client.get_integration_status()

print(f"OKX API连通: {status['okx_api_connected']}")
print(f"配置可用: {status['binance_config_available']}")
print(f"符号映射: {status['symbol_mapping_available']}")
print(f"交易对数量: {status['recommended_symbols_count']}")
print(f"系统就绪: {status['integration_ready']}")
```

#### 动态配置更新

```python
# 动态更新qlib配置
success = client.update_qlib_config(
    enable=True,
    min_confidence=0.8,
    watch_symbols=['BTC-USDT-SWAP', 'ETH-USDT-SWAP'],
    signal_weight=0.4
)
```

#### 自动错误恢复

- **连接断开**: 自动重连okx_strategy API
- **配置更新**: 自动检测并应用配置变更
- **数据缺失**: 自动补充历史数据
- **符号错误**: 自动修复符号映射问题

### 部署选项

#### 开发模式

```bash
# 开发调试模式
python okx_integration_starter.py analyze \
    --okx-api http://localhost:9090 \
    --http-port 8080 \
    --websocket-port 8765
```

#### 生产模式

```bash
# 生产环境模式
python okx_integration_starter.py full \
    --okx-api http://production-okx:9090 \
    --start-date 2023-01-01 \
    --data-dir /data/qlib/okx_binance \
    --output-dir /var/lib/okx_signals
```

#### Docker部署

```dockerfile
# 使用示例Dockerfile
FROM python:3.9-slim

RUN pip install qlib pandas numpy loguru requests aiohttp websockets

COPY okx_integration_starter.py /app/
CMD ["python", "/app/okx_integration_starter.py", "full"]
```

### 性能优化

- **并发数据收集**: 同时处理多个交易对
- **智能缓存**: 缓存配置和符号映射
- **增量更新**: 仅收集缺失的历史数据  
- **连接复用**: HTTP连接池优化
- **内存管理**: 大数据集流式处理

### 监控和运维

#### 日志监控

```bash
# 实时查看系统日志
tail -f /tmp/qlib_analyzer.log

# 过滤关键事件
grep "集成状态\|符号映射\|信号生成" /tmp/qlib_analyzer.log
```

#### 性能指标

- 数据收集速度（符号/秒）
- 信号生成频率（信号/分钟）
- API响应时间（毫秒）
- 系统内存使用（MB）

## CoinGecko数据收集（原有方案）

> **⚠️ 重要提示**: CoinGecko数据仅包含价格、成交量和市值，**不支持OHLC数据**，因此无法进行完整的策略回测。如需完整功能，请使用上述推荐方案。

### 局限性
- **无OHLC数据**: 缺少开高低收价格，无法进行技术分析
- **不支持回测**: 由于数据不完整，无法进行策略回测
- **功能受限**: 仅适用于价格监控和基础分析

### 使用要求

```bash
pip install -r requirements.txt
```

### 数据集用法
> *CoinGecko数据集仅支持数据检索功能，由于缺少OHLC数据，不支持回测功能。*

## Collector Data


### Crypto Data

#### 1d from Coingecko

```bash

# download from https://api.coingecko.com/api/v3/
python collector.py download_data --source_dir ~/.qlib/crypto_data/source/1d --start 2015-01-01 --end 2021-11-30 --delay 1 --interval 1d

# normalize
python collector.py normalize_data --source_dir ~/.qlib/crypto_data/source/1d --normalize_dir ~/.qlib/crypto_data/source/1d_nor --interval 1d --date_field_name date

# dump data
cd qlib/scripts
python dump_bin.py dump_all --csv_path ~/.qlib/crypto_data/source/1d_nor --qlib_dir ~/.qlib/qlib_data/crypto_data --freq day --date_field_name date --include_fields prices,total_volumes,market_caps

```

### using data

```python
import qlib
from qlib.data import D

qlib.init(provider_uri="~/.qlib/qlib_data/crypto_data")
df = D.features(D.instruments(market="all"), ["$prices", "$total_volumes","$market_caps"], freq="day")
```


### Help
```bash
python collector.py collector_data --help
```

## Parameters

- interval: 1d
- delay: 1

## 📝 最新更新 (v3.2 - 2024年8月)

### 🚀 OKX集成系统增强

#### 智能订单管理
- **实时订单修改**: 支持基于qlib信号变化动态调整订单参数
- **防重复交易**: 5分钟时间窗口防护，避免信号重复触发过度交易
- **订单生命周期追踪**: 完整的订单状态监控和管理

#### ML信号处理优化
- **多维度评分系统**: 技术分析 + ML预测 + 市场情绪综合评估
- **动态风险管理**: 基于信号强度的智能仓位调整
- **实时信号验证**: 多层过滤确保信号质量和交易安全

#### 系统稳定性提升
- **并发安全保护**: 所有交易操作使用读写锁保护
- **自动异常恢复**: 网络断开重连和订单失败重试机制
- **内存优化管理**: 定期清理缓存和过期数据，避免内存泄漏

#### 数据流增强
```
Binance数据收集 → qlib ML分析 → 信号验证 → 重复检查 → OKX执行 → 实时调整
```

#### 配置与监控
- **环境变量驱动**: 动态配置管理，支持运行时参数调整
- **智能符号映射**: 自动处理BTCUSDT → BTC-USDT-SWAP转换
- **详细日志系统**: 完整的交易决策和执行过程记录

### 🔄 向下兼容

所有现有的qlib集成代码无需修改即可使用新功能。新版本在保持向后兼容的同时，提供了显著的稳定性和性能提升。

### 🛡️ 生产级部署建议

1. **启用防重复检查**: 确保`DUPLICATE_ORDER_CHECK=true`
2. **合理设置时间窗口**: 默认5分钟检查间隔，可根据策略频率调整
3. **监控系统日志**: 关注订单状态和信号处理统计
4. **定期更新ML模型**: 保持qlib模型和特征工程的时效性

这些更新使qlib + OKX集成系统具备了企业级的稳定性和安全性，能够在复杂的生产环境中可靠运行。
