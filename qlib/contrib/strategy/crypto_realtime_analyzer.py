#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Real-time crypto trading signal analyzer for qlib
Provides analysis results to Go trading programs via multiple communication channels
"""

import json
import time
import threading
import queue
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from pathlib import Path
import asyncio
import websockets
import pandas as pd
import numpy as np
from loguru import logger

import qlib
from qlib.data import D
from qlib.model.trainer import task_train
from qlib.workflow import R
from qlib.utils import init_instance_by_config


class CryptoRealtimeAnalyzer:
    """Real-time crypto trading signal analyzer"""
    
    def __init__(
        self,
        qlib_provider_uri: str,
        model_config: Optional[Dict] = None,
        strategy_config: Optional[Dict] = None,
        websocket_port: int = 8765,
        http_port: int = 8080,
        redis_config: Optional[Dict] = None,
        update_interval: int = 60,  # seconds
    ):
        """
        Initialize real-time analyzer
        
        Parameters
        ----------
        qlib_provider_uri: str
            Qlib data provider URI
        model_config: dict
            ML model configuration
        strategy_config: dict  
            Trading strategy configuration
        websocket_port: int
            WebSocket server port for real-time communication
        http_port: int
            HTTP API port
        redis_config: dict
            Redis configuration for message queue
        update_interval: int
            Analysis update interval in seconds
        """
        self.qlib_provider_uri = qlib_provider_uri
        self.model_config = model_config or self._default_model_config()
        self.strategy_config = strategy_config or self._default_strategy_config()
        self.websocket_port = websocket_port
        self.http_port = http_port
        self.redis_config = redis_config
        self.update_interval = update_interval
        
        # Initialize qlib
        qlib.init(provider_uri=qlib_provider_uri, region="us")
        
        # Analysis state
        self.model = None
        self.last_analysis = {}
        self.analysis_queue = queue.Queue()
        self.is_running = False
        self.websocket_clients = set()
        
        # Initialize components
        self._init_model()
        self._init_redis()
        
        logger.info("CryptoRealtimeAnalyzer initialized")

    def _default_model_config(self) -> Dict:
        """Default ML model configuration"""
        return {
            "class": "LGBModel",
            "module_path": "qlib.contrib.model.gbdt",
            "kwargs": {
                "loss": "mse",
                "colsample_bytree": 0.8879,
                "learning_rate": 0.0421,
                "subsample": 0.8789,
                "lambda_l1": 205.6999,
                "lambda_l2": 580.9768,
                "max_depth": 8,
                "num_leaves": 210,
                "num_threads": 20,
            },
        }

    def _default_strategy_config(self) -> Dict:
        """Default trading strategy configuration"""
        return {
            "class": "TopkDropoutStrategy",
            "module_path": "qlib.contrib.strategy.signal_strategy",
            "kwargs": {"signal": ["Ref($close, -2) / Ref($close, -1) - 1"], "topk": 50, "n_drop": 5},
        }

    def _init_model(self):
        """Initialize ML model"""
        try:
            self.model = init_instance_by_config(self.model_config)
            logger.info("ML model initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize model: {e}")
            self.model = None

    def _init_redis(self):
        """Initialize Redis connection"""
        self.redis_client = None
        if self.redis_config:
            try:
                import redis
                self.redis_client = redis.Redis(**self.redis_config)
                self.redis_client.ping()
                logger.info("Redis connection established")
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}")

    def get_crypto_signals(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        Generate trading signals for crypto symbols
        
        Parameters
        ----------
        symbols: List[str]
            List of crypto symbols to analyze
            
        Returns
        -------
        Dict[str, Dict]
            Trading signals for each symbol
        """
        signals = {}
        
        for symbol in symbols:
            try:
                # Get recent data
                data = D.features(
                    D.instruments([symbol]), 
                    ["$open", "$high", "$low", "$close", "$volume"],
                    freq="day"
                )
                
                if data.empty:
                    logger.warning(f"No data available for {symbol}")
                    continue
                
                # Calculate technical indicators
                signal_data = self._calculate_indicators(data)
                
                # Generate ML prediction if model available
                prediction = None
                if self.model is not None:
                    try:
                        prediction = self._generate_ml_signals(data)
                    except Exception as e:
                        logger.warning(f"ML prediction failed for {symbol}: {e}")
                
                # Combine signals
                signals[symbol] = {
                    'timestamp': datetime.now().isoformat(),
                    'symbol': symbol,
                    'price': float(data['$close'].iloc[-1]) if not data.empty else 0,
                    'volume': float(data['$volume'].iloc[-1]) if not data.empty else 0,
                    'technical_signals': signal_data,
                    'ml_prediction': prediction,
                    'recommendation': self._generate_recommendation(signal_data, prediction),
                    'confidence': self._calculate_confidence(signal_data, prediction),
                }
                
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}")
                signals[symbol] = {
                    'timestamp': datetime.now().isoformat(),
                    'symbol': symbol,
                    'error': str(e),
                    'recommendation': 'HOLD',
                    'confidence': 0.0,
                }
        
        return signals

    def _calculate_indicators(self, data: pd.DataFrame) -> Dict:
        """Calculate technical indicators"""
        try:
            close_prices = data['$close'].values
            high_prices = data['$high'].values
            low_prices = data['$low'].values
            volumes = data['$volume'].values
            
            # Moving averages
            ma_5 = np.mean(close_prices[-5:]) if len(close_prices) >= 5 else close_prices[-1]
            ma_20 = np.mean(close_prices[-20:]) if len(close_prices) >= 20 else close_prices[-1]
            ma_50 = np.mean(close_prices[-50:]) if len(close_prices) >= 50 else close_prices[-1]
            
            # RSI
            rsi = self._calculate_rsi(close_prices)
            
            # MACD
            macd_line, macd_signal = self._calculate_macd(close_prices)
            
            # Bollinger Bands
            bb_upper, bb_lower = self._calculate_bollinger_bands(close_prices)
            
            current_price = close_prices[-1]
            
            return {
                'ma_5': float(ma_5),
                'ma_20': float(ma_20), 
                'ma_50': float(ma_50),
                'rsi': float(rsi),
                'macd_line': float(macd_line),
                'macd_signal': float(macd_signal),
                'bb_upper': float(bb_upper),
                'bb_lower': float(bb_lower),
                'price_vs_ma5': float((current_price - ma_5) / ma_5 * 100),
                'price_vs_ma20': float((current_price - ma_20) / ma_20 * 100),
                'volume_avg': float(np.mean(volumes[-20:]) if len(volumes) >= 20 else volumes[-1]),
            }
        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
            return {}

    def _calculate_rsi(self, prices: np.ndarray, period: int = 14) -> float:
        """Calculate RSI indicator"""
        if len(prices) < period + 1:
            return 50.0
            
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _calculate_macd(self, prices: np.ndarray) -> tuple:
        """Calculate MACD indicator"""
        if len(prices) < 26:
            return 0.0, 0.0
            
        # Exponential moving averages
        ema_12 = self._calculate_ema(prices, 12)
        ema_26 = self._calculate_ema(prices, 26)
        
        macd_line = ema_12 - ema_26
        macd_signal = self._calculate_ema(np.array([macd_line]), 9)
        
        return macd_line, macd_signal

    def _calculate_ema(self, prices: np.ndarray, period: int) -> float:
        """Calculate Exponential Moving Average"""
        if len(prices) < period:
            return np.mean(prices)
            
        multiplier = 2 / (period + 1)
        ema = prices[0]
        
        for price in prices[1:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
            
        return ema

    def _calculate_bollinger_bands(self, prices: np.ndarray, period: int = 20, std_dev: int = 2) -> tuple:
        """Calculate Bollinger Bands"""
        if len(prices) < period:
            mean_price = np.mean(prices)
            std_price = np.std(prices)
        else:
            mean_price = np.mean(prices[-period:])
            std_price = np.std(prices[-period:])
        
        upper_band = mean_price + (std_price * std_dev)
        lower_band = mean_price - (std_price * std_dev)
        
        return upper_band, lower_band

    def _generate_ml_signals(self, data: pd.DataFrame) -> Optional[Dict]:
        """Generate ML-based trading signals"""
        # This is a placeholder for ML prediction
        # In practice, you would use your trained model here
        return {
            'prediction': 0.0,
            'confidence': 0.5,
            'features_used': list(data.columns),
        }

    def _generate_recommendation(self, technical_signals: Dict, ml_prediction: Optional[Dict]) -> str:
        """Generate trading recommendation"""
        try:
            # Technical analysis based recommendation
            rsi = technical_signals.get('rsi', 50)
            price_vs_ma5 = technical_signals.get('price_vs_ma5', 0)
            price_vs_ma20 = technical_signals.get('price_vs_ma20', 0)
            macd_line = technical_signals.get('macd_line', 0)
            macd_signal = technical_signals.get('macd_signal', 0)
            
            bullish_signals = 0
            bearish_signals = 0
            
            # RSI signals
            if rsi < 30:
                bullish_signals += 1
            elif rsi > 70:
                bearish_signals += 1
            
            # Moving average signals
            if price_vs_ma5 > 2 and price_vs_ma20 > 0:
                bullish_signals += 1
            elif price_vs_ma5 < -2 and price_vs_ma20 < 0:
                bearish_signals += 1
            
            # MACD signals
            if macd_line > macd_signal:
                bullish_signals += 1
            else:
                bearish_signals += 1
            
            # Final recommendation
            if bullish_signals > bearish_signals:
                return "BUY"
            elif bearish_signals > bullish_signals:
                return "SELL"
            else:
                return "HOLD"
                
        except Exception as e:
            logger.error(f"Error generating recommendation: {e}")
            return "HOLD"

    def _calculate_confidence(self, technical_signals: Dict, ml_prediction: Optional[Dict]) -> float:
        """Calculate confidence score for the recommendation"""
        try:
            confidence = 0.5  # Base confidence
            
            # Adjust based on RSI strength
            rsi = technical_signals.get('rsi', 50)
            if rsi < 20 or rsi > 80:
                confidence += 0.2
            elif rsi < 30 or rsi > 70:
                confidence += 0.1
            
            # Adjust based on ML prediction if available
            if ml_prediction and 'confidence' in ml_prediction:
                ml_conf = ml_prediction['confidence']
                confidence = (confidence + ml_conf) / 2
            
            return min(1.0, max(0.0, confidence))
            
        except Exception as e:
            logger.error(f"Error calculating confidence: {e}")
            return 0.5

    async def websocket_handler(self, websocket, path):
        """Handle WebSocket connections"""
        self.websocket_clients.add(websocket)
        logger.info(f"WebSocket client connected: {websocket.remote_address}")
        
        try:
            async for message in websocket:
                try:
                    request = json.loads(message)
                    response = await self._handle_websocket_request(request)
                    await websocket.send(json.dumps(response))
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({"error": "Invalid JSON"}))
                except Exception as e:
                    await websocket.send(json.dumps({"error": str(e)}))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.websocket_clients.remove(websocket)
            logger.info(f"WebSocket client disconnected")

    async def _handle_websocket_request(self, request: Dict) -> Dict:
        """Handle WebSocket request"""
        action = request.get('action')
        
        if action == 'get_signals':
            symbols = request.get('symbols', [])
            if not symbols:
                return {"error": "No symbols provided"}
            
            signals = self.get_crypto_signals(symbols)
            return {"action": "signals", "data": signals}
        
        elif action == 'subscribe':
            symbols = request.get('symbols', [])
            return {"action": "subscribed", "symbols": symbols}
        
        else:
            return {"error": f"Unknown action: {action}"}

    async def broadcast_signals(self, signals: Dict):
        """Broadcast signals to all WebSocket clients"""
        if not self.websocket_clients:
            return
            
        message = json.dumps({
            "action": "signal_update",
            "timestamp": datetime.now().isoformat(),
            "data": signals
        })
        
        # Send to all connected clients
        disconnected = set()
        for client in self.websocket_clients:
            try:
                await client.send(message)
            except websockets.exceptions.ConnectionClosed:
                disconnected.add(client)
        
        # Remove disconnected clients
        self.websocket_clients -= disconnected

    def start_websocket_server(self):
        """Start WebSocket server"""
        logger.info(f"Starting WebSocket server on port {self.websocket_port}")
        start_server = websockets.serve(self.websocket_handler, "localhost", self.websocket_port)
        asyncio.get_event_loop().run_until_complete(start_server)

    def publish_to_redis(self, channel: str, data: Dict):
        """Publish data to Redis channel"""
        if self.redis_client:
            try:
                self.redis_client.publish(channel, json.dumps(data))
                logger.debug(f"Published to Redis channel {channel}")
            except Exception as e:
                logger.error(f"Redis publish failed: {e}")

    def analysis_loop(self, symbols: List[str]):
        """Main analysis loop"""
        logger.info(f"Starting analysis loop for symbols: {symbols}")
        
        while self.is_running:
            try:
                # Generate signals
                signals = self.get_crypto_signals(symbols)
                self.last_analysis = signals
                
                # Broadcast via WebSocket
                if self.websocket_clients:
                    asyncio.run(self.broadcast_signals(signals))
                
                # Publish to Redis
                self.publish_to_redis("crypto_signals", signals)
                
                # Add to queue for HTTP API
                try:
                    self.analysis_queue.put_nowait(signals)
                except queue.Full:
                    # Remove old items if queue is full
                    try:
                        self.analysis_queue.get_nowait()
                        self.analysis_queue.put_nowait(signals)
                    except queue.Empty:
                        pass
                
                logger.info(f"Analysis completed for {len(signals)} symbols")
                
            except Exception as e:
                logger.error(f"Analysis loop error: {e}")
            
            time.sleep(self.update_interval)

    def start_analysis(self, symbols: List[str]):
        """Start real-time analysis"""
        self.is_running = True
        
        # Start analysis in separate thread
        analysis_thread = threading.Thread(
            target=self.analysis_loop,
            args=(symbols,),
            daemon=True
        )
        analysis_thread.start()
        
        logger.info("Real-time analysis started")

    def stop_analysis(self):
        """Stop real-time analysis"""
        self.is_running = False
        logger.info("Real-time analysis stopped")

    def get_latest_signals(self) -> Dict:
        """Get latest analysis results"""
        return self.last_analysis

    def export_signals_to_file(self, filepath: str, format: str = "json"):
        """Export latest signals to file"""
        try:
            if format.lower() == "json":
                with open(filepath, 'w') as f:
                    json.dump(self.last_analysis, f, indent=2)
            elif format.lower() == "csv":
                # Convert to DataFrame and save as CSV
                data = []
                for symbol, signals in self.last_analysis.items():
                    row = {"symbol": symbol}
                    row.update(signals.get("technical_signals", {}))
                    row["recommendation"] = signals.get("recommendation", "HOLD")
                    row["confidence"] = signals.get("confidence", 0.0)
                    data.append(row)
                
                df = pd.DataFrame(data)
                df.to_csv(filepath, index=False)
                
            logger.info(f"Signals exported to {filepath}")
            
        except Exception as e:
            logger.error(f"Export failed: {e}")


# Example usage and configuration
if __name__ == "__main__":
    # Example configuration
    analyzer = CryptoRealtimeAnalyzer(
        qlib_provider_uri="~/.qlib/qlib_data/crypto_data",
        websocket_port=8765,
        update_interval=30,  # 30 seconds
    )
    
    # Example crypto symbols
    symbols = ["BTCUSDT", "ETHUSDT", "ADAUSDT", "DOTUSDT"]
    
    # Start analysis
    analyzer.start_analysis(symbols)
    
    # Start WebSocket server in separate thread
    ws_thread = threading.Thread(target=analyzer.start_websocket_server, daemon=True)
    ws_thread.start()
    
    try:
        # Keep running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        analyzer.stop_analysis()
        print("Analysis stopped")