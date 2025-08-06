# 加密货币数据收集系统

本目录提供了多种加密货币数据收集解决方案，支持完整的OHLC数据获取和策略回测功能。

## 🎯 推荐方案

| 数据源 | 成本 | OHLC支持 | 推荐程度 | 文档 |
|--------|------|----------|----------|------|
| **Binance API** | 免费 | ✅ 完整 | ⭐⭐⭐⭐⭐ | [README_Binance.md](./README_Binance.md) |
| TradingView | $14.95/月 | ✅ 完整 | ⭐⭐⭐ | [README_TradingView.md](./README_TradingView.md) |
| CoinGecko | 免费 | ❌ 仅价格 | ⭐⭐ | 本文档 |

**🔥 强烈推荐**: 使用 **[Binance API方案](./README_Binance.md)**，它提供完全免费的OHLC数据、实时分析和Go程序集成。

## 🏗️ 系统架构概览

### 完整解决方案对比

| 功能模块 | Binance方案 | TradingView方案 | CoinGecko方案 |
|----------|------------|----------------|---------------|
| **数据收集器** | `binance_collector.py` | `tradingview_collector.py` | `collector.py` |
| **数据转换器** | `binance_dump_bin.py` | `tradingview_dump_bin.py` | `dump_bin.py` |
| **系统启动器** | `binance_analyzer_starter.py` | `start_crypto_analyzer.py` | 无 |
| **Go客户端** | `binance_go_client_example.go` | 生成的Go代码 | 无 |
| **OHLC支持** | ✅ 完整 | ✅ 完整 | ❌ 仅价格 |
| **回测能力** | ✅ 支持 | ✅ 支持 | ❌ 不支持 |
| **成本** | 免费 | $14.95/月 | 免费 |

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
