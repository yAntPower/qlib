# Repository Guidelines

## Overview & Signal Flow
This repo hosts the ML signal generator that feeds `/home/ant/project/okx_strategy`. Data collectors under `scripts/data_collector/crypto/` pull Binance data, feature pipelines train AutoGluon + River models, and the WebSocket/HTTP services (ports 8080, 8090, 8091) expose BUY/SELL signals in the `{symbol,type,confidence}` format. Keep qlib operable as a standalone service and preserve protocol compatibility with the trading engine.

## Environment Setup
Always activate the shared Python environment at `/home/ant/project/.venv` and execute scripts with `/home/ant/project/.venv/bin/python3`. Configuration shared with OKX lives in `/home/ant/project/okx_strategy/.env`. Before running, ensure models exist in `~/.qlib/production_ml_models/` and the expected data directories (`~/.qlib/binance_simple_data/`, `~/.qlib/binance_hourly_data/`) are populated.

## Strategy Runtime Commands
- `autogluon_river_strategy.py --websocket` (port 8091) is the recommended live service.
- `binance_analyzer_starter.py full --start-date 2023-01-01 --limit-nums 20 --update-interval 30` runs the technical-analysis fallback on port 8080.
- `production_ml_strategy.py [--hourly|--backtest --symbol BTCUSDT]` drives the legacy ensemble for hourly/daily or backtest runs.
- Health checks: `curl http://localhost:8091/{health,signals,metrics}`.

## Data Management
- Incremental updates: `/home/ant/project/.venv/bin/python3 binance_collector.py --symbol BTCUSDT --start 2021-01-01`.
- Hourly batch download: `./download_hourly_data.sh` from the crypto directory.
- Format conversion: `/home/ant/project/.venv/bin/python3 binance_dump_bin.py --symbol BTCUSDT`.
- Full refresh + retrain:
  - AutoGluon + River: run the inline snippet constructing `AutoGluonRiverStrategy(use_hourly_data=True)` and call `force_download_all_hourly_data()` then `retrain_all_models()`.
  - Legacy ensemble: use the analogous `EnhancedProductionML` snippet.

## Configuration & Tuning
Key env vars (`ML_SLIPPAGE`, `ML_TAKER_FEE`, `ML_DEAD_ZONE`, `ML_MIN_CONFIDENCE`, `ML_MIN_HOLDING_PERIODS`) guard trading costs and overtrading. Model settings include `ML_USE_BINARY_CLASSIFICATION=true`, `ML_LABEL_STRATEGY=adaptive`, and the up/down thresholds (`0.004/-0.004`). Update them via shell exports before launching services; document changes in PR descriptions.

## Testing, Monitoring & Logs
Use `/home/ant/project/.venv/bin/python3 production_ml_strategy.py --backtest --symbol BTCUSDT` for regression checks. Monitor runtime with `tail -f /tmp/qlib_analyzer.log`, `/tmp/enhanced_production_ml.log`, and cross-reference `/home/ant/project/okx_strategy/logs/strategy_*.log`. Validate WebSocket ports are free (`lsof -i:8091`) and re-run setup scripts if models or data regressed.

## Integration Guidelines
When coordinating with okx_strategy remote mode, modify only signal-generation code and maintain the event payload contract. Local or hybrid strategy changes belong in the Go repo. Keep language for runbooks and PRs in Chinese unless bilingual context is required, mirroring the trading project workflow.
