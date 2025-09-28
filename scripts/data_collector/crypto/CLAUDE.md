# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a cryptocurrency trading strategy system built on Microsoft Qlib framework, located in `/home/ant/project/qlib/scripts/data_collector/crypto/`. The system includes data collection, technical analysis, machine learning models, and HTTP API services for crypto trading signals.

## Environment Setup

**IMPORTANT: Always use the virtual environment for Python execution**
- Python virtual environment: `/home/ant/project/.venv`
- Execute Python scripts with: `/home/ant/project/.venv/bin/python3`
- Configuration file for OKX integration: `/home/ant/project/okx_strategy/.env`

## Key Commands

### Running Strategies

```bash
# ALWAYS use virtual environment
cd /home/ant/project/qlib/scripts/data_collector/crypto

# AutoGluon+River Strategy (RECOMMENDED - port 8091)
/home/ant/project/.venv/bin/python3 autogluon_river_strategy.py --websocket

# Technical Analysis Strategy (port 8080)
/home/ant/project/.venv/bin/python3 binance_analyzer_starter.py full --start-date 2023-01-01 --limit-nums 20 --update-interval 30

# Production ML Strategy (Legacy - port 8091)
/home/ant/project/.venv/bin/python3 production_ml_strategy.py          # Daily data
/home/ant/project/.venv/bin/python3 production_ml_strategy.py --hourly  # Hourly data
```

### Data Management

```bash
# Update historical data
/home/ant/project/.venv/bin/python3 binance_collector.py --symbol BTCUSDT --start 2021-01-01

# Download hourly data
./download_hourly_data.sh

# Convert data format
/home/ant/project/.venv/bin/python3 binance_dump_bin.py --symbol BTCUSDT

# Force re-download all hourly data (complete historical data from 2021)
/home/ant/project/.venv/bin/python3 -c "
from production_ml_strategy import EnhancedProductionML
ml = EnhancedProductionML(use_hourly_data=True)
ml.force_download_all_hourly_data()  # Download ~40,000 hourly records per symbol
"
```

### Testing & Validation

```bash
# Run backtest
/home/ant/project/.venv/bin/python3 production_ml_strategy.py --backtest --symbol BTCUSDT

# Check strategy status
curl http://localhost:8091/health
curl http://localhost:8091/signals
curl http://localhost:8091/metrics
```

### Integrated System with OKX

```bash
# Start integrated system with AutoGluon+River (RECOMMENDED)
cd /home/ant/project/okx_strategy
./scripts/start_integrated_system.sh --strategy autogluon

# Alternative strategies
./scripts/start_integrated_system.sh --strategy hourly      # Production ML with hourly data
./scripts/start_integrated_system.sh --strategy technical  # Technical analysis

# System management
./scripts/start_integrated_system.sh stop
./scripts/start_integrated_system.sh restart
./scripts/start_integrated_system.sh status

# Data and model management
./scripts/start_integrated_system.sh download-data  # Re-download all hourly data
./scripts/start_integrated_system.sh retrain       # Retrain all models
./scripts/start_integrated_system.sh retrain-all   # Download data + retrain
```

### Environment Variables for Strategy Configuration

```bash
# Trading cost parameters
export ML_SLIPPAGE=0.0005           # Slippage (default 0.05%)
export ML_TAKER_FEE=0.001          # Taker fee (default 0.1%)
export ML_MAKER_FEE=0.0008         # Maker fee (default 0.08%)

# Overtrading prevention
export ML_DEAD_ZONE=0.05           # Dead zone range (default 5%)
export ML_MIN_CONFIDENCE=0.6       # Minimum confidence (default 60%)
export ML_MIN_HOLDING_PERIODS=4    # Minimum holding hours (default 4)
export ML_EXCLUDE_UNCLOSED_BAR=true # Exclude unclosed bars

# Model parameters
export ML_USE_BINARY_CLASSIFICATION=true
export ML_LABEL_STRATEGY=adaptive  # adaptive/percentile/volatility_adjusted
export ML_UP_THRESHOLD=0.004
export ML_DOWN_THRESHOLD=-0.004
```

## Architecture

### Project Integration
- **qlib project**: ML strategy analysis and signal generation (this directory)
- **okx_strategy project**: Signal reception and OKX exchange execution (`/home/ant/project/okx_strategy`)
- **Communication**: WebSocket between qlib and okx_strategy
- **Signal format**: `{"symbol": "BTCUSDT", "type": "long/short/HOLD", "confidence": 0.8}`

### Core Components

1. **Data Collection Layer** (`binance_collector.py`, `tradingview_collector.py`)
   - Fetches historical and real-time data from exchanges
   - Stores in `~/.qlib/binance_simple_data/` (daily) and `~/.qlib/binance_hourly_data/` (hourly)

2. **Strategy Layer**
   - `autogluon_river_strategy.py`: AutoGluon AutoML + River online learning (RECOMMENDED)
   - `binance_analyzer_starter.py`: Pure technical indicators (RSI, MACD, Bollinger Bands)
   - `production_ml_strategy.py`: Legacy ensemble ML (XGBoost + LightGBM + RF + GradientBoosting)

3. **Feature Engineering** (in `production_ml_strategy.py`)
   - `_create_enhanced_features()`: 100+ technical indicators
   - `_compute_features()`: Combines price, volume, volatility features
   - Automatic feature selection using SelectKBest (top 60 features)

4. **Model Management**
   - AutoGluon models: `~/.qlib/autogluon_models/` (AutoML models)
   - River models: `~/.qlib/river_models/` (Online learning models)
   - Legacy production models: `~/.qlib/production_ml_models/` (binary classification)
   - Auto-retraining: Daily at UTC 12:00 (Beijing 20:00)
   - Performance monitoring with metrics tracking

5. **Data Storage Paths**
   - **Source data (raw)**: 
     - Daily: `~/.qlib/binance_simple_data/*.csv`
     - Hourly: `~/.qlib/binance_hourly_data/*.csv` (40,000+ records per symbol from 2021)
   - **Trained models**: 
     - `~/.qlib/autogluon_models/` - AutoGluon AutoML models
     - `~/.qlib/river_models/` - River online learning models
     - `~/.qlib/production_ml_models/` - Legacy ensemble models
   - **Model files**: 
     - AutoGluon: `{SYMBOL}_autogluon/` directories
     - River: `{SYMBOL}_river_model.pkl`
     - Legacy: `{SYMBOL}_model.pkl`, `{SYMBOL}_scaler.pkl`, `{SYMBOL}_features.pkl`

5. **HTTP API Service**
   - Flask-based REST API on ports 8080/8090/8091
   - Endpoints: `/health`, `/signals`, `/metrics`, `/retrain`
   - WebSocket support via `websocket_server.py`

### Data Flow

```
Exchange API → Data Collector → CSV Storage → Feature Engineering → 
ML Model → Prediction → Signal Generation → HTTP API → Trading System
```

## Critical Implementation Details

### Recent Fixes (2025-08-31)

1. **Trading Costs**: Now includes both taker fees and slippage in backtest calculations
2. **Unclosed Bars**: Automatically excludes the latest unclosed candlestick to avoid unstable signals
3. **Overtrading Prevention**: 
   - Dead zone filter (holds position when probability near 0.5)
   - Minimum confidence threshold (default 60%)
   - Minimum holding period (default 4 hours)

### Model Training Process

The production ML strategy uses:
- TimeSeriesSplit for cross-validation (5 splits)
- SMOTE for handling imbalanced data
- Ensemble of 4 models with weighted voting:
  - XGBoost (35%)
  - LightGBM (35%)
  - RandomForest (20%)
  - GradientBoosting (10%)

### Signal Generation

1. Load latest market data (excluding unclosed bar if configured)
2. Compute 100+ technical features
3. Apply feature selection (top 60 features)
4. Scale features using RobustScaler
5. Generate ensemble prediction
6. Apply filters (dead zone, confidence, holding period)
7. Integrate market sentiment (Fear & Greed Index)
8. Return final signal with confidence score

## Dependencies

Core requirements from `requirements_binance.txt`:
- qlib>=0.8.0
- pandas, numpy, requests
- scikit-learn>=1.0.0
- lightgbm>=3.3.0
- catboost>=1.0.0
- xgboost (optional but recommended)
- imblearn (for SMOTE)

## Integration Points

### OKX Strategy Integration
The system integrates with OKX trading execution via WebSocket:
- WebSocket communication between qlib and okx_strategy
- Signal processing with duplicate prevention (5-minute window)
- Risk management validation before execution

Configuration:
```bash
export QLIB_HTTP_URL=http://localhost:8091
export QLIB_MIN_CONFIDENCE=0.6
```

### Supported Trading Pairs
- BTCUSDT
- ETHUSDT
- SUIUSDT
- SOLUSDT
- ADAUSDT
- DOGEUSDT

### Market Sentiment
Fetches Fear & Greed Index from Alternative.me API and integrates into signal generation.

## Performance Metrics

Current model performance (3-class classification):
- BTCUSDT: ~42% accuracy
- ETHUSDT: ~40% accuracy
- SOLUSDT: ~39% accuracy
- Typical Sharpe Ratio: 1.4-2.5
- Max Drawdown: <1% (with proper risk management)

Note: 40% accuracy on 3-class problem is better than random (33.3%).

## Development Notes

### Important: Mode Isolation Principle
- **When modifying for okx_strategy remote mode**: Only modify qlib-related signal generation logic
- **When modifying for okx_strategy local mode**: Do NOT modify qlib code at all
- **Signal format consistency**: Always maintain the same signal format for WebSocket/HTTP communication
- **Independence**: qlib project should work independently without depending on specific okx_strategy implementation

### Critical Guidelines
- **CRITICAL**: Always use virtual environment `/home/ant/project/.venv/bin/python3`
- Always check if models exist before generating signals
- Use `logger` for debugging (configured with loguru)
- Backtesting should exclude future data (using `.shift(1)`)
- Feature importance is tracked in `~/.qlib/production_ml_models/*_importance.json`
- Auto-retraining runs daily at UTC 12:00 (Beijing 20:00)
- Binary classification mode is used in production (BUY/SELL only, no HOLD)
- Label strategy: percentile (70/30) for production

## Log File Locations

- **Main qlib analyzer log**: `/tmp/qlib_analyzer.log` - WebSocket server and signal generation
- **Enhanced ML strategy log**: `/tmp/enhanced_production_ml.log` - Detailed ML model training and predictions
- **OKX integration logs**: See `/home/ant/project/okx_strategy/logs/strategy_*.log`

## Common Issues & Solutions

1. **Port already in use**: Check with `lsof -i:PORT` and kill existing process
2. **Low model accuracy**: Normal for crypto markets; ensure sufficient training data
3. **Memory issues**: Reduce `data_window` or use fewer features
4. **API rate limits**: Implement exponential backoff in data collectors
5. **Python module not found**: Ensure using virtual environment `/home/ant/project/.venv/bin/python3`
6. **Model file not found**: Check if models exist in `~/.qlib/production_ml_models/`

## Manual Model Retraining

```bash
cd /home/ant/project/qlib/scripts/data_collector/crypto

# AutoGluon+River strategy (RECOMMENDED)
/home/ant/project/.venv/bin/python3 -c "
from autogluon_river_strategy import AutoGluonRiverStrategy
ml = AutoGluonRiverStrategy(use_hourly_data=True)
ml.retrain_all_models()
"

# Legacy production strategy
/home/ant/project/.venv/bin/python3 -c "
from production_ml_strategy import EnhancedProductionML
ml = EnhancedProductionML(use_hourly_data=True)
ml.retrain_all_models()
"
```

## 2025-09 重要更新：AutoGluon+River集成

### 核心变化
系统已简化为使用AutoGluon+River组合，删除了复杂的CatBoost和其他旧模型代码。

### 新增文件
1. **autogluon_river_strategy.py** - AutoGluon+River集成策略
   - AutoGluon自动机器学习（离线批训练）
   - River在线学习（实时模型更新）
   - 专为i5-7700 + 16GB RAM + GTX 1060配置优化
   - 支持WebSocket通信和HTTP API

### 已删除的文件（简化系统）
- `crypto_enhanced_features.py` - 移除复杂特征工程
- `crypto_advanced_models.py` - 移除CatBoost等高级模型
- `enhanced_crypto_ml_strategy.py` - 移除增强集成策略
- `crypto_automl_strategy.py` - 移除旧的AutoML实现
- 所有CatBoost相关配置和脚本文件

### 依赖更新
```bash
pip install river       # v0.22.0，在线学习核心库
pip install autogluon   # 自动机器学习（已安装）
# 不再需要：catboost, TA-Lib等复杂依赖
```

### 配置参数调整
- `ML_MIN_CONFIDENCE=0.45` (从0.55降低)
- `ML_DEAD_ZONE=0.005` (从0.01降低)
- 更激进的信号生成策略，适合AutoGluon的自动优化特性

## Data Download and Management

### Force Re-download Complete Historical Data

When data is incomplete or corrupted, use the force download function:

```bash
cd /home/ant/project/qlib/scripts/data_collector/crypto

# AutoGluon+River strategy (RECOMMENDED)
/home/ant/project/.venv/bin/python3 -c "
from autogluon_river_strategy import AutoGluonRiverStrategy
import logging
logging.basicConfig(level=logging.INFO)

ml = AutoGluonRiverStrategy(use_hourly_data=True)

# Force download all historical data (2021-present)
ml.force_download_all_hourly_data()

# Then retrain models with new data
ml.retrain_all_models()
"

# Legacy production strategy
/home/ant/project/.venv/bin/python3 -c "
from production_ml_strategy import EnhancedProductionML
import logging
logging.basicConfig(level=logging.INFO)

ml = EnhancedProductionML(use_hourly_data=True)
ml.force_download_all_hourly_data()
ml.retrain_all_models()
"
```

### Data Specifications

- **Training data volume**: ~40,000 hourly records per symbol (4+ years from 2021)
- **SMOTE balancing**: Reduces to ~33,000 samples after 80/20 train/test split and class balancing
- **Special handling for new tokens**:
  - SUI: Data from 2023-05-03 (launch date)
  - Other major tokens: Data from 2021-01-01
- **Download batch size**: 1000 records per API call
- **Complete download time**: ~2-3 minutes per symbol

## 2025-09-25 信号记录和分析系统

### JSONL信号记录功能
AutoGluon+River策略现已集成自动信号记录功能，所有生成的交易信号会自动保存到JSONL文件。

#### 实现细节
- **存储路径**: `~/.qlib/signal_logs/`
- **文件命名**: `signals_YYYYMMDD.jsonl`（按日期自动轮转）
- **记录内容**: 所有信号（包括HOLD），含完整元数据
- **线程安全**: 使用锁机制确保并发写入安全
- **自动启用**: 无需额外配置，策略启动后自动记录

#### 记录的数据字段
```json
{
  "symbol": "BTCUSDT",
  "type": "long/short/hold",
  "recommendation": "BUY/SELL/HOLD",
  "confidence": 0.75,
  "buy_prob": 0.65,
  "raw_buy_prob": 0.63,
  "adjusted_prob": 0.64,
  "price": 42000.5,
  "models_used": 2,
  "timestamp": "2025-09-25T12:00:00",
  "logged_at": "2025-09-25T12:00:01",
  "reason": "BUY | raw=0.63 cal=0.65 (q20=0.45, q80=0.78)",
  "decision_mode": "quantile",
  "quantiles": {"q20": 0.45, "q50": 0.55, "q80": 0.78},
  "source": "autogluon_river_fixed",
  "log_type": "realtime_signal"
}
```

### 信号分析工具
新增专门的分析工具 `analyze_signals.py` 用于处理和分析JSONL信号记录。

#### 主要功能
1. **数据加载**: 批量加载历史信号文件
2. **统计分析**: 信号分布、置信度统计、币种分析
3. **模式识别**: 时间模式、连续信号、高置信度信号
4. **报告生成**: 美观的表格化报告
5. **回测导出**: 导出标准CSV格式供回测使用

#### 使用示例
```bash
# 分析最近7天的信号
/home/ant/project/.venv/bin/python3 /home/ant/project/qlib/scripts/data_collector/crypto/analyze_signals.py

# 分析特定日期
/home/ant/project/.venv/bin/python3 /home/ant/project/qlib/scripts/data_collector/crypto/analyze_signals.py --date 20250925

# 分析30天数据并生成报告
/home/ant/project/.venv/bin/python3 /home/ant/project/qlib/scripts/data_collector/crypto/analyze_signals.py --days 30 --output analysis_report.txt

# 导出CSV用于回测
/home/ant/project/.venv/bin/python3 /home/ant/project/qlib/scripts/data_collector/crypto/analyze_signals.py --export signals_for_backtest.csv

# 分析高置信度信号（>0.8）
/home/ant/project/.venv/bin/python3 /home/ant/project/qlib/scripts/data_collector/crypto/analyze_signals.py --threshold 0.8

# 指定自定义日志目录
/home/ant/project/.venv/bin/python3 /home/ant/project/qlib/scripts/data_collector/crypto/analyze_signals.py --dir /path/to/signals
```

#### 分析报告内容
- **基本统计**: 总信号数、币种数量、时间范围、平均置信度
- **信号分布**: BUY/SELL/HOLD的数量和比例
- **币种统计**: 每个币种的详细信号统计表
- **高置信度信号**: 筛选并分析置信度超过阈值的信号
- **时间模式**: 按小时的信号分布，识别活跃时段
- **连续信号**: 分析同方向连续出现的信号模式

### 应用场景
1. **策略优化**: 通过分析历史信号改进模型参数
2. **性能监控**: 跟踪模型表现随时间的变化
3. **回测验证**: 使用真实历史信号进行回测
4. **问题诊断**: 调试信号生成逻辑和模型预测
5. **报告生成**: 为投资决策提供数据支持

### 数据管理建议
- 信号日志文件会持续增长，建议定期归档旧文件
- JSONL格式便于流式处理大文件，无需全部加载到内存
- 可以使用标准UNIX工具（如jq、grep）直接处理JSONL文件
- 建议保留至少30天的信号记录用于分析

### 新增依赖
- tabulate 0.9.0 - 用于生成美观的表格报告

## 生产环境最佳实践要求

### 核心原则
该系统用于**真实生产环境交易**，不是模拟或测试程序。所有功能实现必须遵循生产环境最高标准。

### 关键功能要求（必须严格执行）

1. **模型训练**:
   - 数据质量保证（去重、异常值处理、时间序列完整性检查）
   - 训练稳定性（错误重试、checkpoint保存、训练中断恢复）
   - 模型版本管理（保留历史版本、支持回滚）
   - 避免数据泄漏（严格时间分割、前向验证）

2. **交易信号生成**:
   - 信号可靠性验证（多重确认机制）
   - 延迟控制（毫秒级响应）
   - 信号去重和防抖动
   - 置信度计算准确性

3. **数据管理**:
   - 历史数据完整性保证
   - 实时数据断线重连
   - 数据备份和恢复机制
   - 增量更新优化

4. **回测系统**:
   - 避免前视偏差
   - 真实滑点和手续费计算
   - 准确的资金曲线统计
   - Walk-forward分析

5. **特征工程**:
   - 特征稳定性验证
   - 特征重要性追踪
   - 特征版本控制
   - 实时特征计算优化

### 次要功能要求（可适当简化）
- UI界面美观性
- 报表格式规范
- 非核心日志详细程度
- 辅助工具完整性

### 代码标准
- 错误处理：所有外部调用必须有异常捕获和重试机制
- 日志记录：关键操作必须留痕，便于问题追踪
- 性能优化：信号生成路径必须优化到极致
- 测试覆盖：核心逻辑必须有单元测试