# Qlib加密货币交易模块完整指南

## 📍 模块位置
- **核心目录**: `/home/ant/project/qlib/scripts/data_collector/crypto/`
- **数据目录**: `~/.qlib/binance_simple_data/` (历史数据)
- **模型目录**: `~/.qlib/production_ml_models/` (ML模型)

## 🏗️ 系统架构

### 1. 数据收集模块
**位置**: `scripts/data_collector/crypto/`

#### Binance数据收集器（主要使用）
- `binance_collector.py` - Binance API数据收集
- `binance_dump_bin.py` - 数据格式转换
- `binance_normalize.py` - 数据标准化
- **数据范围**: 2021年至今，1686+天日线数据

#### 其他数据源（备选）
- `tradingview_collector.py` - TradingView数据（需付费）
- `collector.py` - CoinGecko数据（仅价格）

### 2. 策略分析模块

#### 技术分析策略
- **文件**: `enhanced_binance_starter.py`
- **端口**: 8080
- **特点**: 纯技术指标，无需训练，响应快速
- **指标**: RSI, MACD, 布林带, ATR等

#### ML智能策略（原始版）
- **文件**: `ml_strategy_analyzer.py`
- **端口**: 8090
- **特点**: RandomForest基础模型，快速训练
- **数据**: 使用最近1000条数据

#### 生产级ML策略（推荐）
- **文件**: `production_ml_strategy.py`
- **端口**: 8091
- **特点**: 
  - LightGBM + RandomForest + GradientBoosting集成
  - 使用2021年至今全量数据（1686+天）
  - 100+技术特征，自动特征选择
  - 动态阈值调整
  - 包含完整回测系统
- **准确率**: 40%+（3分类问题）

### 3. HTTP API服务
所有策略都提供统一的HTTP API：
- `/health` - 健康检查
- `/signals` - 获取交易信号
- `/metrics` - 查看模型指标（ML策略）
- `/retrain` - 重新训练模型（ML策略）

## 🚀 快速启动

### 1. 启动技术分析策略
```bash
cd /home/ant/project/qlib/scripts/data_collector/crypto
./start_technical_strategy.sh
# 或直接运行
python enhanced_binance_starter.py
```

### 2. 启动ML策略
```bash
# 原始ML策略
./start_ml_strategy.sh

# 生产级ML策略（推荐）
./start_production_ml.sh
```

### 3. 查看所有策略状态
```bash
./status_strategies.sh
```

## 📊 数据管理

### 历史数据位置
```
~/.qlib/binance_simple_data/
├── BTCUSDT_1d.csv  (2021-01-01 至今)
├── ETHUSDT_1d.csv  (2021-01-01 至今)
├── SOLUSDT_1d.csv  (2021-01-01 至今)
├── ADAUSDT_1d.csv  (2021-01-01 至今)
└── SUIUSDT_1d.csv  (2023-05-03 至今)
```

### 数据更新
```python
# 使用binance_collector.py更新数据
python binance_collector.py --symbol BTCUSDT --start 2021-01-01
```

## 🤖 ML模型管理

### 模型文件
```
~/.qlib/production_ml_models/
├── BTCUSDT_ensemble.pkl     # 集成模型
├── BTCUSDT_scaler.pkl       # 数据缩放器
├── BTCUSDT_selector.pkl     # 特征选择器
├── BTCUSDT_metrics.json     # 性能指标
└── BTCUSDT_importance.json  # 特征重要性
```

### 模型性能
- BTCUSDT: 42.28% 准确率
- ETHUSDT: 40.60% 准确率
- SOLUSDT: 39.60% 准确率
- ADAUSDT: 38.93% 准确率

## 🔧 配置与集成

### OKX集成配置
```bash
# 使用技术分析
export QLIB_HTTP_URL=http://localhost:8080
export QLIB_MIN_CONFIDENCE=0.6

# 使用ML策略
export QLIB_HTTP_URL=http://localhost:8090  # 或8091(生产级)
export QLIB_MIN_CONFIDENCE=0.5

# 启动OKX策略
cd /home/ant/project/okx_strategy
./okx-strategy
```

### 策略切换脚本
```bash
# 位置: /home/ant/project/okx_strategy/switch_strategy.sh
./switch_strategy.sh technical  # 技术分析
./switch_strategy.sh ml         # ML策略
./switch_strategy.sh hybrid     # 混合模式
```

## 📝 开发指南

### 添加新的技术指标
编辑 `enhanced_binance_starter.py`，在 `calculate_indicators()` 函数中添加。

### 训练新的ML模型
```python
from production_ml_strategy import ProductionMLStrategy

# 创建策略实例
strategy = ProductionMLStrategy(
    symbols=['BTCUSDT', 'ETHUSDT'],
    use_hourly_data=False  # 使用日线数据
)

# 重新训练所有模型
strategy.retrain_all_models()

# 运行回测
strategy.backtest('BTCUSDT', start_date='2023-01-01')
```

### 自定义特征工程
编辑 `production_ml_strategy.py` 中的 `_create_advanced_features()` 方法。

## 🔍 故障排查

### 常见问题

1. **端口被占用**
```bash
# 查看占用端口的进程
lsof -i:8080
# 停止策略
./stop_technical_strategy.sh
```

2. **模型准确率低**
- 正常现象，加密货币市场难以预测
- 3分类问题，40%已优于随机(33.3%)
- 持续收集数据会逐步改善

3. **数据更新失败**
- 检查网络连接
- 确认Binance API可访问
- 查看日志: `/tmp/qlib_analyzer.log`

## 📊 性能优化建议

1. **数据质量**
   - 定期更新历史数据
   - 考虑添加小时级数据（未来）

2. **模型优化**
   - 调整特征选择数量(当前50个)
   - 尝试不同的集成权重
   - 实现在线学习

3. **风险管理**
   - 设置止损/止盈
   - 控制仓位大小
   - 多策略投票决策

## 🚨 重要提醒

1. **这是个人使用的交易系统，请谨慎使用**
2. **加密货币交易风险极高**
3. **历史表现不代表未来收益**
4. **建议先小额测试**
5. **保持策略更新和优化**

## 📚 相关资源

- Microsoft Qlib官方文档: https://qlib.readthedocs.io/
- Binance API文档: https://binance-docs.github.io/apidocs/
- LightGBM文档: https://lightgbm.readthedocs.io/

---

最后更新: 2025-08-13
策略版本: v3.2