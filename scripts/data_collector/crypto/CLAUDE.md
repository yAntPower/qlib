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

# Technical Analysis Strategy (port 8080)
/home/ant/project/.venv/bin/python3 enhanced_binance_starter.py

# ML Strategy - Basic (port 8090)
/home/ant/project/.venv/bin/python3 ml_strategy_analyzer.py

# Production ML Strategy (port 8091)
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
# Start integrated system (ML strategy + OKX execution)
cd /home/ant/project/okx_strategy
./scripts/start_integrated_system.sh --strategy hourly

# Stop system
./scripts/start_integrated_system.sh stop

# Restart system
./scripts/start_integrated_system.sh restart

# Check status
./scripts/start_integrated_system.sh status
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
   - `enhanced_binance_starter.py`: Pure technical indicators (RSI, MACD, Bollinger Bands)
   - `ml_strategy_analyzer.py`: Basic RandomForest ML model
   - `production_ml_strategy.py`: Advanced ensemble ML (XGBoost + LightGBM + RF + GradientBoosting)

3. **Feature Engineering** (in `production_ml_strategy.py`)
   - `_create_enhanced_features()`: 100+ technical indicators
   - `_compute_features()`: Combines price, volume, volatility features
   - Automatic feature selection using SelectKBest (top 60 features)

4. **Model Management**
   - Production models: `~/.qlib/production_ml_models/` (binary classification)
   - Hourly models: `~/.qlib/hourly_models/`
   - Includes ensemble models, scalers, feature selectors
   - Auto-retraining: Daily at UTC 12:00 (Beijing 20:00)
   - Performance monitoring with metrics tracking

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

- **CRITICAL**: Always use virtual environment `/home/ant/project/.venv/bin/python3`
- Always check if models exist before generating signals
- Use `logger` for debugging (configured with loguru)
- Backtesting should exclude future data (using `.shift(1)`)
- Feature importance is tracked in `~/.qlib/production_ml_models/*_importance.json`
- Auto-retraining runs daily at UTC 12:00 (Beijing 20:00)
- Binary classification mode is used in production (BUY/SELL only, no HOLD)
- Label strategy: percentile (70/30) for production

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
/home/ant/project/.venv/bin/python3 -c "
from production_ml_strategy import ProductionMLStrategy
ml = ProductionMLStrategy(use_hourly_data=True)
ml.retrain_all_models()
"
```