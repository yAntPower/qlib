"""Utility for loading and scoring backtest results exported by okx_strategy."""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from glob import glob
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class BacktestRecord:
    symbol: str
    okx_symbol: str
    timeframe: str
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe: float
    sortino: float
    calmar: float
    profit_factor: float
    win_rate: float
    total_trades: int
    generated_at: datetime
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def quality(self) -> str:
        """Derive a coarse quality label for downstream usage."""
        if self.total_return >= 0.08 and self.max_drawdown <= 0.18 and self.sharpe >= 1.0:
            return "strong"
        if self.total_return <= 0 or self.max_drawdown >= 0.28 or self.sharpe <= 0:
            return "weak"
        return "neutral"


class BacktestRepository:
    def __init__(self, base_dir: Optional[str], refresh_interval: int = 300):
        self.base_dir = os.path.expanduser(base_dir) if base_dir else None
        self.refresh_interval = refresh_interval
        self._last_scan_ts: float = 0.0
        self._cache: Dict[str, BacktestRecord] = {}
        self._file_mtimes: Dict[str, float] = {}

        if not self.base_dir:
            logger.warning("Backtest repository base directory not provided; backtest integration disabled")
        else:
            logger.info("Backtest repository watching %s", self.base_dir)

    def refresh(self, force: bool = False) -> None:
        if not self.base_dir:
            return
        now = time.time()
        if not force and now - self._last_scan_ts < self.refresh_interval:
            return

        pattern = os.path.join(self.base_dir, "*.json")
        files = glob(pattern)
        for path in files:
            try:
                mtime = os.path.getmtime(path)
                if self._file_mtimes.get(path) == mtime:
                    continue

                with open(path, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)

                record = self._parse_payload(payload, path)
                if not record:
                    self._file_mtimes[path] = mtime
                    continue

                key = self._normalize_symbol(record.symbol)
                current = self._cache.get(key)
                if not current or record.generated_at >= current.generated_at:
                    self._cache[key] = record
                    logger.info(
                        "Loaded backtest summary for %s (quality=%s, total_return=%.2f%%)",
                        record.symbol,
                        record.quality,
                        record.total_return * 100,
                    )

                self._file_mtimes[path] = mtime
            except Exception as exc:
                logger.warning("Failed to load backtest file %s: %s", path, exc)
        self._last_scan_ts = now

    def get_latest(self, symbol: str) -> Optional[BacktestRecord]:
        self.refresh()
        key = self._normalize_symbol(symbol)
        return self._cache.get(key)

    def as_dict(self, record: BacktestRecord) -> Dict[str, Any]:
        return {
            "symbol": record.symbol,
            "timeframe": record.timeframe,
            "total_return": record.total_return,
            "annualized_return": record.annualized_return,
            "max_drawdown": record.max_drawdown,
            "sharpe": record.sharpe,
            "sortino": record.sortino,
            "calmar": record.calmar,
            "profit_factor": record.profit_factor,
            "win_rate": record.win_rate,
            "total_trades": record.total_trades,
            "quality": record.quality,
            "generated_at": record.generated_at.isoformat(),
        }

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        if not symbol:
            return ""
        symbol = symbol.strip().upper()
        symbol = symbol.replace("-SWAP", "")
        symbol = symbol.replace("-USDT", "USDT")
        symbol = symbol.replace("-", "")
        return symbol

    def _parse_payload(self, payload: Dict[str, Any], path: str) -> Optional[BacktestRecord]:
        try:
            if payload.get("type") != "backtest_result":
                return None

            symbol = payload.get("symbol") or ""
            timeframe = payload.get("timeframe", "")
            risk = payload.get("risk", {})
            returns = payload.get("returns", {})
            trades = payload.get("trades", {})

            generated_at_raw = payload.get("generated_at") or payload.get("metadata", {}).get("generated_at")
            if generated_at_raw:
                generated_at = datetime.fromisoformat(generated_at_raw.replace("Z", "+00:00"))
            else:
                generated_at = datetime.utcnow()

            return BacktestRecord(
                symbol=symbol,
                okx_symbol=symbol,
                timeframe=timeframe,
                total_return=float(returns.get("total", 0.0)),
                annualized_return=float(returns.get("annualized", 0.0)),
                max_drawdown=float(risk.get("max_drawdown", 0.0)),
                sharpe=float(risk.get("sharpe", 0.0)),
                sortino=float(risk.get("sortino", 0.0)),
                calmar=float(risk.get("calmar", 0.0)),
                profit_factor=float(trades.get("profit_factor", 0.0)),
                win_rate=float(trades.get("win_rate", 0.0)),
                total_trades=int(trades.get("total_trades", 0)),
                generated_at=generated_at,
                raw=payload,
            )
        except Exception as exc:
            logger.warning("Unable to parse backtest file %s: %s", path, exc)
            return None

    def describe(self) -> Dict[str, Dict[str, Any]]:
        self.refresh()
        return {key: self.as_dict(record) for key, record in self._cache.items()}
