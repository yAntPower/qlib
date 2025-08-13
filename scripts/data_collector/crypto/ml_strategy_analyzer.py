#!/usr/bin/env python3
"""
AI智能加密货币策略分析系统
使用机器学习模型进行价格预测和交易信号生成
"""

import os
import sys
import time
import json
import pickle
import logging
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import warnings
warnings.filterwarnings('ignore')

# 机器学习库
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score
import joblib

# 深度学习（如果可用）
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    print("PyTorch not available, using sklearn models only")

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/ml_strategy.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

if TORCH_AVAILABLE:
    class LSTMPredictor(nn.Module):
        """LSTM深度学习模型用于价格预测"""
        def __init__(self, input_size, hidden_size=128, num_layers=2, output_size=3):
            super(LSTMPredictor, self).__init__()
            self.hidden_size = hidden_size
            self.num_layers = num_layers
            
            self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True, dropout=0.2)
            self.fc1 = nn.Linear(hidden_size, 64)
            self.fc2 = nn.Linear(64, output_size)
            self.dropout = nn.Dropout(0.2)
            self.relu = nn.ReLU()
            self.softmax = nn.Softmax(dim=1)
            
        def forward(self, x):
            h0 = torch.zeros(self.num_layers, x.size(0), self.hidden_size)
            c0 = torch.zeros(self.num_layers, x.size(0), self.hidden_size)
            
            out, _ = self.lstm(x, (h0, c0))
            out = self.fc1(out[:, -1, :])
            out = self.relu(out)
            out = self.dropout(out)
            out = self.fc2(out)
            out = self.softmax(out)
            return out

class MLStrategyAnalyzer:
    """AI智能策略分析器"""
    
    def __init__(self, data_dir="~/.qlib/binance_simple_data", model_dir="~/.qlib/ml_models"):
        self.data_dir = Path(data_dir).expanduser()
        self.model_dir = Path(model_dir).expanduser()
        self.model_dir.mkdir(parents=True, exist_ok=True)
        
        self.base_url = "https://api.binance.com"
        self.symbols = self._load_symbols_from_config()
        
        # 模型存储
        self.models = {}
        self.scalers = {}
        self.lstm_models = {}
        
        # 特征配置
        self.feature_window = 30  # 使用30天的历史数据作为特征
        self.prediction_horizon = 1  # 预测未来1天
        
        # 信号存储
        self.signals = {}
        
        # 加载或训练模型
        self._initialize_models()
    
    def _load_symbols_from_config(self):
        """加载交易对配置"""
        default_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "SUIUSDT"]
        env_symbols = os.environ.get('QLIB_WATCH_SYMBOLS')
        if env_symbols:
            symbols = []
            for symbol in env_symbols.split(','):
                symbol = symbol.strip()
                if '-USDT-SWAP' in symbol:
                    binance_symbol = symbol.replace('-USDT-SWAP', 'USDT').replace('-', '')
                    symbols.append(binance_symbol)
                elif 'USDT' in symbol:
                    symbols.append(symbol)
            if symbols:
                logger.info(f"从环境变量加载币种: {symbols}")
                return symbols
        
        logger.info(f"使用默认币种列表: {default_symbols}")
        return default_symbols
    
    def _initialize_models(self):
        """初始化或加载模型"""
        for symbol in self.symbols:
            model_path = self.model_dir / f"{symbol}_model.pkl"
            scaler_path = self.model_dir / f"{symbol}_scaler.pkl"
            lstm_path = self.model_dir / f"{symbol}_lstm.pth"
            
            if model_path.exists() and scaler_path.exists():
                # 加载已有模型
                logger.info(f"加载 {symbol} 的已有模型")
                self.models[symbol] = joblib.load(model_path)
                self.scalers[symbol] = joblib.load(scaler_path)
                
                if TORCH_AVAILABLE and lstm_path.exists():
                    self.lstm_models[symbol] = torch.load(lstm_path)
            else:
                # 训练新模型
                logger.info(f"训练 {symbol} 的新模型")
                self._train_model(symbol)
    
    def _prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """准备机器学习特征"""
        features = pd.DataFrame()
        
        # 价格相关特征
        features['returns'] = df['close'].pct_change()
        features['log_returns'] = np.log(df['close'] / df['close'].shift(1))
        features['price_range'] = (df['high'] - df['low']) / df['close']
        features['price_position'] = (df['close'] - df['low']) / (df['high'] - df['low'])
        
        # 成交量特征
        features['volume_ratio'] = df['volume'] / df['volume'].rolling(20).mean()
        features['volume_change'] = df['volume'].pct_change()
        
        # 技术指标特征
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        features['rsi'] = 100 - (100 / (1 + rs))
        
        # 移动平均线
        for period in [5, 10, 20, 50]:
            features[f'ma_{period}'] = df['close'].rolling(period).mean()
            features[f'ma_{period}_ratio'] = df['close'] / features[f'ma_{period}']
        
        # MACD
        exp1 = df['close'].ewm(span=12).mean()
        exp2 = df['close'].ewm(span=26).mean()
        features['macd'] = exp1 - exp2
        features['macd_signal'] = features['macd'].ewm(span=9).mean()
        features['macd_histogram'] = features['macd'] - features['macd_signal']
        
        # 布林带
        bb_period = 20
        bb_std = df['close'].rolling(bb_period).std()
        bb_mean = df['close'].rolling(bb_period).mean()
        features['bb_upper'] = bb_mean + (bb_std * 2)
        features['bb_lower'] = bb_mean - (bb_std * 2)
        features['bb_position'] = (df['close'] - features['bb_lower']) / (features['bb_upper'] - features['bb_lower'])
        
        # 波动率特征
        features['volatility'] = df['close'].pct_change().rolling(20).std()
        features['atr'] = self._calculate_atr(df)
        
        # 市场微结构特征
        features['spread'] = (df['high'] - df['low']) / df['close']
        features['close_to_high'] = (df['high'] - df['close']) / df['close']
        features['close_to_low'] = (df['close'] - df['low']) / df['close']
        
        # 滞后特征（过去N天的收益）
        for i in range(1, 8):
            features[f'lag_return_{i}'] = features['returns'].shift(i)
        
        # 滚动统计特征
        for window in [5, 10, 20]:
            features[f'rolling_mean_{window}'] = features['returns'].rolling(window).mean()
            features[f'rolling_std_{window}'] = features['returns'].rolling(window).std()
            features[f'rolling_max_{window}'] = df['high'].rolling(window).max()
            features[f'rolling_min_{window}'] = df['low'].rolling(window).min()
        
        return features
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算ATR（平均真实范围）"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        return atr
    
    def _create_labels(self, df: pd.DataFrame, threshold: float = 0.01) -> pd.Series:
        """创建训练标签（未来价格方向）"""
        future_returns = df['close'].shift(-self.prediction_horizon) / df['close'] - 1
        
        # 三分类：下跌(-1)、横盘(0)、上涨(1)
        labels = pd.Series(index=df.index, dtype=int)
        labels[future_returns < -threshold] = 0  # 下跌
        labels[future_returns > threshold] = 2   # 上涨
        labels[(future_returns >= -threshold) & (future_returns <= threshold)] = 1  # 横盘
        
        return labels
    
    def _train_model(self, symbol: str):
        """训练机器学习模型"""
        # 加载历史数据
        df = self._load_historical_data(symbol)
        if df is None or len(df) < 100:
            logger.warning(f"{symbol} 数据不足，跳过训练")
            return
        
        # 准备特征和标签
        features = self._prepare_features(df)
        labels = self._create_labels(df)
        
        # 删除NaN值
        valid_idx = ~(features.isna().any(axis=1) | labels.isna())
        features = features[valid_idx]
        labels = labels[valid_idx]
        
        if len(features) < 100:
            logger.warning(f"{symbol} 有效数据不足，跳过训练")
            return
        
        # 分割训练集和测试集
        X_train, X_test, y_train, y_test = train_test_split(
            features, labels, test_size=0.2, shuffle=False
        )
        
        # 标准化特征
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # 训练集成模型
        logger.info(f"训练 {symbol} 的随机森林模型...")
        rf_model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            min_samples_split=5,
            random_state=42,
            n_jobs=-1
        )
        rf_model.fit(X_train_scaled, y_train)
        
        # 评估模型
        y_pred = rf_model.predict(X_test_scaled)
        accuracy = accuracy_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred, average='weighted', zero_division=0)
        recall = recall_score(y_test, y_pred, average='weighted', zero_division=0)
        
        logger.info(f"{symbol} 模型性能 - 准确率: {accuracy:.3f}, 精确率: {precision:.3f}, 召回率: {recall:.3f}")
        
        # 保存模型
        self.models[symbol] = rf_model
        self.scalers[symbol] = scaler
        
        model_path = self.model_dir / f"{symbol}_model.pkl"
        scaler_path = self.model_dir / f"{symbol}_scaler.pkl"
        joblib.dump(rf_model, model_path)
        joblib.dump(scaler, scaler_path)
        
        # 训练LSTM模型（如果PyTorch可用）
        if TORCH_AVAILABLE and len(X_train) > 200:
            self._train_lstm_model(symbol, X_train_scaled, y_train, X_test_scaled, y_test)
    
    def _train_lstm_model(self, symbol: str, X_train, y_train, X_test, y_test):
        """训练LSTM深度学习模型"""
        logger.info(f"训练 {symbol} 的LSTM模型...")
        
        # 准备序列数据
        sequence_length = min(30, len(X_train) // 10)
        X_train_seq = self._create_sequences(X_train, sequence_length)
        y_train_seq = y_train[sequence_length:]
        X_test_seq = self._create_sequences(X_test, sequence_length)
        y_test_seq = y_test[sequence_length:]
        
        # 转换为PyTorch张量
        X_train_tensor = torch.FloatTensor(X_train_seq)
        y_train_tensor = torch.LongTensor(y_train_seq.values)
        X_test_tensor = torch.FloatTensor(X_test_seq)
        y_test_tensor = torch.LongTensor(y_test_seq.values)
        
        # 创建模型
        input_size = X_train.shape[1]
        model = LSTMPredictor(input_size)
        
        # 训练模型
        criterion = nn.CrossEntropyLoss()
        optimizer = optim.Adam(model.parameters(), lr=0.001)
        
        epochs = 50
        batch_size = 32
        
        for epoch in range(epochs):
            model.train()
            for i in range(0, len(X_train_tensor), batch_size):
                batch_X = X_train_tensor[i:i+batch_size]
                batch_y = y_train_tensor[i:i+batch_size]
                
                optimizer.zero_grad()
                outputs = model(batch_X)
                loss = criterion(outputs, batch_y)
                loss.backward()
                optimizer.step()
            
            if (epoch + 1) % 10 == 0:
                model.eval()
                with torch.no_grad():
                    test_outputs = model(X_test_tensor)
                    _, predicted = torch.max(test_outputs.data, 1)
                    test_accuracy = (predicted == y_test_tensor).sum().item() / len(y_test_tensor)
                    logger.info(f"Epoch {epoch+1}/{epochs}, Test Accuracy: {test_accuracy:.3f}")
        
        # 保存LSTM模型
        self.lstm_models[symbol] = model
        lstm_path = self.model_dir / f"{symbol}_lstm.pth"
        torch.save(model, lstm_path)
    
    def _create_sequences(self, data, sequence_length):
        """创建LSTM输入序列"""
        sequences = []
        for i in range(len(data) - sequence_length):
            sequences.append(data[i:i+sequence_length])
        return np.array(sequences)
    
    def _load_historical_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """加载历史数据"""
        file_path = self.data_dir / f"{symbol}_1d.csv"
        
        if file_path.exists():
            df = pd.read_csv(file_path)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp')
            return df
        
        # 如果没有本地数据，从API获取
        logger.info(f"下载 {symbol} 的历史数据...")
        df = self._fetch_historical_data(symbol)
        if df is not None and not df.empty:
            df.to_csv(file_path, index=False)
        return df
    
    def _fetch_historical_data(self, symbol: str, days: int = 365) -> Optional[pd.DataFrame]:
        """从Binance API获取历史数据"""
        url = f"{self.base_url}/api/v3/klines"
        params = {
            'symbol': symbol,
            'interval': '1d',
            'limit': min(days, 1000)
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if not data:
                return None
            
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col])
            
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
            
        except Exception as e:
            logger.error(f"获取 {symbol} 历史数据失败: {e}")
            return None
    
    def generate_ai_signal(self, symbol: str) -> Optional[Dict]:
        """生成AI交易信号"""
        try:
            # 获取最新数据
            df = self._load_historical_data(symbol)
            if df is None or len(df) < 50:
                return None
            
            # 获取实时数据更新
            latest_data = self._fetch_historical_data(symbol, days=2)
            if latest_data is not None and not latest_data.empty:
                # 更新最新数据
                df = pd.concat([df[:-1], latest_data.tail(1)], ignore_index=True)
            
            # 准备特征
            features = self._prepare_features(df)
            if features.empty or features.iloc[-1].isna().any():
                return None
            
            latest_features = features.iloc[-1:].values
            
            # 检查是否有训练好的模型
            if symbol not in self.models or symbol not in self.scalers:
                logger.warning(f"{symbol} 没有可用的模型")
                return None
            
            # 标准化特征
            scaler = self.scalers[symbol]
            latest_features_scaled = scaler.transform(latest_features)
            
            # 使用集成模型预测
            rf_model = self.models[symbol]
            rf_proba = rf_model.predict_proba(latest_features_scaled)[0]
            
            # 如果有LSTM模型，也使用它预测
            lstm_proba = None
            if TORCH_AVAILABLE and symbol in self.lstm_models:
                lstm_model = self.lstm_models[symbol]
                lstm_model.eval()
                
                # 准备LSTM输入序列
                recent_features = features.iloc[-30:].values
                recent_features_scaled = scaler.transform(recent_features)
                lstm_input = torch.FloatTensor(recent_features_scaled).unsqueeze(0)
                
                with torch.no_grad():
                    lstm_output = lstm_model(lstm_input)
                    lstm_proba = lstm_output.numpy()[0]
            
            # 综合预测结果
            if lstm_proba is not None:
                # 结合RF和LSTM预测（各占50%权重）
                final_proba = 0.5 * rf_proba + 0.5 * lstm_proba
            else:
                final_proba = rf_proba
            
            # 生成交易信号
            prediction = np.argmax(final_proba)
            confidence = float(final_proba[prediction])
            
            # 映射预测结果到交易建议
            if prediction == 2:  # 上涨
                recommendation = "BUY"
                signal_strength = confidence
            elif prediction == 0:  # 下跌
                recommendation = "SELL"
                signal_strength = confidence
            else:  # 横盘
                recommendation = "HOLD"
                signal_strength = 0.5
            
            # 添加额外的市场分析
            current_price = float(df['close'].iloc[-1])
            current_rsi = float(features['rsi'].iloc[-1])
            current_volume = float(df['volume'].iloc[-1])
            
            # 生成详细的分析理由
            reasons = []
            
            # 基于AI预测
            if confidence > 0.7:
                reasons.append(f"AI高置信度预测 ({confidence:.1%})")
            elif confidence > 0.6:
                reasons.append(f"AI中等置信度预测 ({confidence:.1%})")
            
            # 基于技术指标
            if current_rsi < 30:
                reasons.append(f"RSI超卖 ({current_rsi:.1f})")
            elif current_rsi > 70:
                reasons.append(f"RSI超买 ({current_rsi:.1f})")
            
            # 基于价格动量
            price_change = (current_price - float(df['close'].iloc[-2])) / float(df['close'].iloc[-2])
            if abs(price_change) > 0.02:
                if price_change > 0:
                    reasons.append(f"价格上涨动量 (+{price_change:.1%})")
                else:
                    reasons.append(f"价格下跌动量 ({price_change:.1%})")
            
            # 计算风险评分
            volatility = float(features['volatility'].iloc[-1]) if not pd.isna(features['volatility'].iloc[-1]) else 0.02
            risk_score = min(1.0, volatility * 10)  # 将波动率转换为0-1的风险分数
            
            return {
                'symbol': symbol,
                'timestamp': datetime.now().isoformat(),
                'recommendation': recommendation,
                'confidence': confidence,
                'price': current_price,
                'volume': current_volume,
                'ai_prediction': {
                    'direction': ['DOWN', 'HOLD', 'UP'][prediction],
                    'probability_down': float(final_proba[0]),
                    'probability_hold': float(final_proba[1]),
                    'probability_up': float(final_proba[2]),
                    'model_type': 'LSTM+RF' if lstm_proba is not None else 'RF',
                },
                'technical_indicators': {
                    'rsi': current_rsi,
                    'ma_5': float(features['ma_5'].iloc[-1]) if 'ma_5' in features else current_price,
                    'ma_20': float(features['ma_20'].iloc[-1]) if 'ma_20' in features else current_price,
                    'macd': float(features['macd'].iloc[-1]) if 'macd' in features else 0,
                    'volatility': volatility,
                    'atr': float(features['atr'].iloc[-1]) if 'atr' in features else 0,
                },
                'risk_metrics': {
                    'risk_score': risk_score,
                    'risk_level': 'HIGH' if risk_score > 0.7 else 'MEDIUM' if risk_score > 0.4 else 'LOW',
                    'suggested_position_size': max(0.1, 1.0 - risk_score),  # 风险越高，仓位越小
                },
                'signal_strength': signal_strength,
                'reasons': reasons
            }
            
        except Exception as e:
            logger.error(f"生成 {symbol} AI信号失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def update_all_signals(self):
        """更新所有交易对的AI信号"""
        for symbol in self.symbols:
            signal = self.generate_ai_signal(symbol)
            if signal:
                self.signals[symbol] = signal
                logger.info(f"{symbol}: {signal['recommendation']} "
                          f"(AI置信度: {signal['confidence']:.2f}, "
                          f"风险: {signal['risk_metrics']['risk_level']})")
    
    def retrain_models(self):
        """重新训练所有模型（应该定期执行）"""
        logger.info("开始重新训练所有模型...")
        for symbol in self.symbols:
            logger.info(f"重新训练 {symbol} 模型...")
            self._train_model(symbol)
        logger.info("所有模型训练完成")

class MLStrategyHTTPHandler(BaseHTTPRequestHandler):
    """HTTP API处理器"""
    
    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        if path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {
                "status": "ok",
                "service": "ml-strategy-analyzer",
                "models_loaded": len(getattr(self.server, 'analyzer', {}).models) if hasattr(self.server, 'analyzer') else 0,
                "timestamp": datetime.now().isoformat()
            }
            self.wfile.write(json.dumps(response).encode())
            
        elif path == '/signals' or path == '/signals/latest':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            analyzer = getattr(self.server, 'analyzer', None)
            if analyzer:
                signals = analyzer.signals.copy()
                response = {
                    "status": "success",
                    "timestamp": datetime.now().isoformat(),
                    "data": signals
                }
            else:
                response = {
                    "status": "error",
                    "timestamp": datetime.now().isoformat(),
                    "data": {},
                    "error": "Analyzer not initialized"
                }
            
            self.wfile.write(json.dumps(response).encode())
            
        elif path == '/retrain':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            analyzer = getattr(self.server, 'analyzer', None)
            if analyzer:
                # 在后台线程中重新训练
                threading.Thread(target=analyzer.retrain_models, daemon=True).start()
                response = {
                    "status": "success",
                    "message": "Model retraining started in background"
                }
            else:
                response = {
                    "status": "error",
                    "message": "Analyzer not initialized"
                }
            
            self.wfile.write(json.dumps(response).encode())
            
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not Found')
    
    def log_message(self, format, *args):
        pass  # 禁用请求日志

def start_http_server(analyzer, port=8090):
    """启动HTTP服务器"""
    try:
        httpd = HTTPServer(('', port), MLStrategyHTTPHandler)
        httpd.analyzer = analyzer
        logger.info(f"HTTP服务器启动在端口 {port}")
        httpd.serve_forever()
    except Exception as e:
        logger.error(f"HTTP服务器错误: {e}")

def main():
    """主函数"""
    print("=" * 60)
    print("🤖 AI智能加密货币策略分析系统")
    print("=" * 60)
    
    try:
        # 创建分析器
        print("🔧 初始化AI分析器...")
        analyzer = MLStrategyAnalyzer()
        
        # 启动HTTP服务器
        http_thread = threading.Thread(
            target=start_http_server,
            args=(analyzer, 8090),
            daemon=True
        )
        http_thread.start()
        
        print("\n✅ AI策略系统启动成功！")
        print(f"📡 HTTP API: http://localhost:8090")
        print(f"📊 监控交易对: {', '.join(analyzer.symbols)}")
        print(f"🧠 已加载模型: {len(analyzer.models)} 个")
        print(f"💾 模型目录: {analyzer.model_dir}")
        print("\n📌 API端点:")
        print("  - GET /health - 健康检查")
        print("  - GET /signals - 获取AI交易信号")
        print("  - GET /retrain - 重新训练模型")
        print("\n🔄 系统运行中... (按 Ctrl+C 停止)")
        
        # 首次更新信号
        print("\n🧠 正在生成AI交易信号...")
        analyzer.update_all_signals()
        
        # 主循环
        update_interval = 300  # 5分钟更新一次
        retrain_interval = 86400  # 24小时重训练一次
        last_retrain = time.time()
        
        while True:
            time.sleep(update_interval)
            
            # 更新信号
            logger.info("更新AI交易信号...")
            analyzer.update_all_signals()
            
            # 检查是否需要重新训练
            if time.time() - last_retrain > retrain_interval:
                logger.info("开始定期模型重训练...")
                analyzer.retrain_models()
                last_retrain = time.time()
                
    except KeyboardInterrupt:
        print("\n⏹️  收到停止信号，正在关闭...")
        print("✅ AI策略系统已停止")
        
    except Exception as e:
        print(f"❌ 系统错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()