# TradingView加密货币数据收集器和实时分析系统

本文档介绍如何使用TradingView数据源为qlib添加完整的加密货币交易策略分析能力，包括OHLC数据支持、回测功能和与Go程序的实时通信。

> **⚠️ 重要提示**: TradingView API需要付费Pro账户。如果您寻找免费的解决方案，请参考 **[README_Binance.md](./README_Binance.md)**，它提供了基于Binance免费API的完整替代方案，包含相同的OHLC数据和交易功能。

## 📊 数据源对比

| 特性 | TradingView | Binance API (推荐) |
|------|-------------|-------------------|
| 💰 成本 | $14.95/月 Pro版本 | **完全免费** |
| 📈 OHLC数据 | ✅ 完整支持 | ✅ 完整支持 |
| 🌍 数据覆盖 | 多交易所聚合 | Binance单一交易所 |
| ⚡ 实时性 | 几分钟延迟 | 毫秒级延迟 |
| 📊 数据质量 | 标准化处理 | 原始交易数据 |
| 🔧 集成难度 | 需要认证 | 无需认证 |
| 📚 历史数据 | Pro用户限制 | 免费获取全部 |

**建议**: 对于大多数用户，我们推荐使用Binance API方案，它提供相同的功能但完全免费。

## 🏗️ TradingView方案架构

### 核心实现模块

```
TradingView加密货币分析系统
├── 📊 数据收集层
│   └── tradingview_collector.py    # TradingView数据收集器
├── 🔄 数据处理层
│   └── tradingview_dump_bin.py    # 数据转换工具  
├── 🚀 系统启动层
│   └── start_crypto_analyzer.py   # 系统启动脚本
├── 🧠 分析决策层
│   └── crypto_realtime_analyzer.py # 实时分析器
├── 🔗 通信接口层
│   └── go_communication.py        # Go通信接口
└── 🤖 客户端层
    └── 动态生成的Go客户端代码
```

### 核心类架构

#### TradingViewCryptoCollector
```python
class TradingViewCryptoCollector(BaseCollector):
    # 时间间隔映射
    INTERVAL_MAPPING = {
        "1d": "1D", "1h": "1H", "4h": "4H",
        "15m": "15", "5m": "5", "1m": "1"
    }
    
    # 核心方法
    def get_crypto_symbols()    # 获取交易对列表
    def get_ohlc_data()        # 获取OHLC数据
    def _authenticate()        # TradingView认证
```

### 与Binance方案的差异

| 特性 | TradingView方案 | Binance方案 |
|------|----------------|-------------|
| 数据源认证 | 需要Pro账户认证 | 无需认证 |
| 数据覆盖范围 | 多交易所聚合 | 单一交易所 |
| 实时性 | 几分钟延迟 | 毫秒级延迟 |
| 成本 | $14.95/月 | 完全免费 |
| 实现复杂度 | 需要处理认证 | 直接API调用 |

## 功能特性

### 🚀 核心功能
- **TradingView数据收集**: 支持从TradingView收集加密货币OHLC数据
- **完整回测支持**: 提供开高低收价格数据，支持完整的策略回测
- **多时间周期**: 支持1分钟、5分钟、15分钟、1小时、4小时、日线数据
- **实时分析**: 基于机器学习和技术指标的实时交易信号分析
- **Go程序集成**: 多种通信方式与Go交易程序集成

### 📊 数据支持
- **OHLC数据**: 开盘价、最高价、最低价、收盘价
- **成交量数据**: 支持成交量分析
- **技术指标**: RSI、MACD、布林带、移动平均线等
- **机器学习预测**: 基于历史数据的价格预测

### 🔗 通信方式
- **WebSocket**: 实时双向通信
- **HTTP API**: RESTful API接口
- **Redis队列**: 消息队列通信
- **文件输出**: JSON/CSV格式信号文件
- **Webhook**: HTTP回调通知

## 安装和依赖

### Python依赖
```bash
# 基础依赖
pip install tradingview-screener websockets redis pandas numpy loguru

# qlib相关依赖
pip install qlib

# 可选依赖
pip install requests aiohttp
```

### Go集成
Go客户端代码已移至专门的okx_strategy项目中，请参考该项目的文档进行集成配置。

## 使用说明

本文档重点介绍TradingView数据收集和Python实时分析系统的配置与使用。完整的部署安装指南（包括Go客户端集成）请参考专门的 **[install.md](../../../../go/okx_strategy/install.md)** 文件。

### 快速开始

1. **数据收集**: 使用CoinGecko或手动TradingView数据
2. **启动分析器**: 运行Python实时分析系统
3. **API接口**: 通过HTTP/WebSocket提供信号
4. **Go集成**: Go客户端代码已移至okx_strategy项目

## 详细配置

### TradingView数据收集器配置

```python
# tradingview_collector.py 参数说明
collector = TradingViewCryptoCollector(
    save_dir="~/.qlib/crypto_tv_data/source/1d",  # 数据保存目录
    start="2023-01-01",                           # 开始日期
    end="2024-12-31",                            # 结束日期
    interval="1d",                               # 时间周期：1m, 5m, 15m, 1h, 4h, 1d
    tv_username="your_username",                 # TradingView用户名
    tv_password="your_password",                 # TradingView密码
    delay=1,                                     # 请求延迟（秒）
    limit_nums=None,                            # 限制符号数量（调试用）
)
```

### 实时分析器配置

```python
analyzer = CryptoRealtimeAnalyzer(
    qlib_provider_uri="~/.qlib/qlib_data/crypto_tv_data",  # qlib数据路径
    model_config={                                         # ML模型配置
        "class": "LGBModel",
        "module_path": "qlib.contrib.model.gbdt",
        "kwargs": {
            "learning_rate": 0.05,
            "max_depth": 8,
            "num_leaves": 210,
        }
    },
    strategy_config={                                      # 策略配置
        "class": "TopkDropoutStrategy",
        "module_path": "qlib.contrib.strategy.signal_strategy",
        "kwargs": {"topk": 50, "n_drop": 5}
    },
    websocket_port=8765,                                   # WebSocket端口
    update_interval=30,                                    # 更新间隔（秒）
)
```

### Go通信接口配置

```python
go_interface = GoTradingInterface(
    analyzer=analyzer,                           # 分析器实例
    http_port=8080,                             # HTTP API端口
    output_dir="/tmp/qlib_crypto_signals",      # 信号输出目录
    redis_config={                              # Redis配置
        "host": "localhost",
        "port": 6379,
        "db": 0
    },
    webhook_url="http://your-server.com/webhook"  # Webhook URL
)
```

## API接口说明

### HTTP API

#### 获取最新信号
```bash
GET /signals/latest
```
返回所有符号的最新交易信号。

#### 获取指定符号信号
```bash
GET /signals?symbols=BTCUSDT,ETHUSDT
```
返回指定符号的交易信号。

#### 获取信号历史
```bash
GET /signals/history?limit=100
```
返回历史信号记录。

#### 健康检查
```bash
GET /health
```
返回系统健康状态。

#### 分析请求
```bash
POST /analyze
Content-Type: application/json

{
    "symbols": ["BTCUSDT", "ETHUSDT"]
}
```
触发指定符号的即时分析。

### WebSocket API

连接到 `ws://localhost:8765`

#### 获取信号
```json
{
    "action": "get_signals",
    "symbols": ["BTCUSDT", "ETHUSDT"]
}
```

#### 订阅更新
```json
{
    "action": "subscribe",
    "symbols": ["BTCUSDT", "ETHUSDT"]
}
```

### Redis队列

#### 订阅信号更新
```python
import redis
r = redis.Redis()
pubsub = r.pubsub()
pubsub.subscribe('crypto_trading_signals')

for message in pubsub.listen():
    if message['type'] == 'message':
        signal_data = json.loads(message['data'])
        # 处理信号数据
```

## 信号格式说明

### 交易信号结构

```json
{
    "BTCUSDT": {
        "timestamp": "2024-01-01T12:00:00",
        "symbol": "BTCUSDT",
        "price": 45000.0,
        "volume": 1000000.0,
        "recommendation": "BUY",        // BUY, SELL, HOLD
        "confidence": 0.85,             // 0.0 - 1.0
        "technical_signals": {
            "ma_5": 44800.0,
            "ma_20": 44500.0,
            "ma_50": 44000.0,
            "rsi": 35.5,
            "macd_line": 100.5,
            "macd_signal": 95.2,
            "bb_upper": 46000.0,
            "bb_lower": 43000.0,
            "price_vs_ma5": 0.45,
            "price_vs_ma20": 1.12,
            "volume_avg": 950000.0
        },
        "ml_prediction": {
            "prediction": 0.15,          // 预测价格变化百分比
            "confidence": 0.75,
            "features_used": ["$open", "$high", "$low", "$close", "$volume"]
        }
    }
}
```

### 文件输出格式

系统会自动生成多种格式的信号文件：

1. **JSON格式** (`latest_signals.json`)
2. **CSV格式** (`latest_signals.csv`)
3. **Go结构体格式** (`signals_YYYYMMDD_HHMMSS.go.json`)

## 策略回测

使用收集的OHLC数据进行策略回测：

```python
import qlib
from qlib.data import D
from qlib.backtest import backtest
from qlib.contrib.strategy import TopkDropoutStrategy

# 初始化qlib
qlib.init(provider_uri="~/.qlib/qlib_data/crypto_tv_data")

# 创建策略
strategy = TopkDropoutStrategy(
    signal=["Ref($close, -2) / Ref($close, -1) - 1"],
    topk=10,
    n_drop=2
)

# 执行回测
result = backtest(
    strategy=strategy,
    start_time="2023-01-01",
    end_time="2023-12-31",
    account=100000,
)

# 分析结果
print(f"总收益: {result['return']:.2%}")
print(f"夏普比率: {result['sharpe']:.3f}")
print(f"最大回撤: {result['max_drawdown']:.2%}")
```

## 性能优化

### 数据收集优化

1. **并发控制**: 设置合适的`max_workers`和`delay`参数
2. **数据分块**: 使用`limit_nums`进行分批处理
3. **缓存机制**: 利用qlib的数据缓存功能

### 实时分析优化

1. **更新频率**: 根据交易频率调整`update_interval`
2. **模型选择**: 使用轻量级模型减少计算开销
3. **内存管理**: 定期清理历史数据

### Go客户端优化

1. **连接池**: 使用HTTP连接池
2. **并发处理**: 使用goroutine并发处理多个信号
3. **错误重试**: 实现指数退避重试机制

## 故障排除

### 常见问题

1. **TradingView认证失败**
   - 检查用户名和密码
   - 确认账户状态正常

2. **数据为空**
   - 检查symbol格式是否正确
   - 确认时间范围设置合理

3. **WebSocket连接失败**
   - 检查端口是否被占用
   - 确认防火墙设置

4. **Redis连接失败**
   - 检查Redis服务状态
   - 确认连接配置正确

### 日志调试

```python
from loguru import logger

# 设置日志级别
logger.remove()
logger.add(sys.stdout, level="DEBUG")

# 启用详细日志
analyzer.start_analysis(symbols, debug=True)
```

## 扩展功能

### 自定义技术指标

```python
def custom_indicator(data):
    """自定义技术指标"""
    # 实现您的指标逻辑
    return indicator_value

# 在分析器中注册
analyzer.register_custom_indicator("my_indicator", custom_indicator)
```

### 自定义交易策略

```python
from qlib.contrib.strategy import BaseStrategy

class CustomCryptoStrategy(BaseStrategy):
    def generate_trade_decision(self, pred_score, current_temp):
        # 实现您的交易逻辑
        return trade_decision
```

### 多交易所支持

系统支持扩展到多个交易所数据源：

```python
# 添加币安数据收集器
from binance_collector import BinanceCryptoCollector

binance_collector = BinanceCryptoCollector(
    api_key="your_api_key",
    api_secret="your_api_secret"
)
```

## 许可证

本项目基于MIT许可证，详见LICENSE文件。

## 贡献指南

欢迎提交Issue和Pull Request来改进本项目。

## 联系我们

如有问题或建议，请通过GitHub Issues联系我们。