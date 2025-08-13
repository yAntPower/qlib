#!/usr/bin/env python3
"""
生产级ML加密货币策略分析器
- 使用全量历史数据（2021-至今）
- 支持XGBoost/LightGBM/CatBoost
- 特征工程优化
- 回测系统
- 动态阈值
"""

import os
import sys
import json
import time
import logging
import warnings
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from http.server import HTTPServer, BaseHTTPRequestHandler
import numpy as np
import pandas as pd

# 机器学习库
from sklearn.model_selection import train_test_split, TimeSeriesSplit, cross_val_score
from sklearn.preprocessing import StandardScaler, RobustScaler
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.feature_selection import SelectKBest, f_classif, RFE
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
from sklearn.metrics import classification_report, confusion_matrix
import joblib

# 尝试导入高级ML库
try:
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False
    print("XGBoost not available, will use LightGBM and RandomForest")

try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False
    print("LightGBM not available, will use RandomForest and GradientBoosting")

warnings.filterwarnings('ignore')

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/production_ml_strategy.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class ProductionMLStrategy:
    """生产级ML策略分析器"""
    
    def __init__(self, 
                 data_dir: str = "~/.qlib/binance_simple_data",
                 model_dir: str = "~/.qlib/production_ml_models",
                 symbols: Optional[List[str]] = None,
                 use_hourly_data: bool = False):
        """
        初始化生产级ML策略
        
        Args:
            data_dir: 数据目录
            model_dir: 模型保存目录
            symbols: 交易对列表
            use_hourly_data: 是否使用小时级数据
        """
        self.data_dir = os.path.expanduser(data_dir)
        self.model_dir = os.path.expanduser(model_dir)
        self.use_hourly_data = use_hourly_data
        
        # 默认交易对
        self.symbols = symbols or ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'ADAUSDT', 'BNBUSDT']
        
        # 模型配置
        self.models = {}
        self.scalers = {}
        self.feature_selectors = {}
        self.feature_importance = {}
        
        # 性能指标
        self.model_metrics = {}
        self.backtest_results = {}
        
        # 参数配置
        self.config = {
            'min_data_points': 500,  # 最少数据点
            'test_size': 0.2,        # 测试集比例
            'n_features': 50,         # 选择的特征数量
            'prediction_horizon': 1,  # 预测周期
            'dynamic_threshold': True,  # 动态阈值
            'threshold_percentile': 70,  # 阈值百分位
            'use_ensemble': True,     # 使用集成模型
            'models_to_use': ['xgboost', 'lightgbm', 'rf', 'gb'],  # 使用的模型（完整集成）
        }
        
        # 创建模型目录
        os.makedirs(self.model_dir, exist_ok=True)
        
        # 初始化模型
        self._initialize_models()
        
        logger.info(f"生产级ML策略初始化完成")
        logger.info(f"数据目录: {self.data_dir}")
        logger.info(f"模型目录: {self.model_dir}")
        logger.info(f"监控币种: {self.symbols}")
    
    def _initialize_models(self):
        """初始化或加载模型"""
        for symbol in self.symbols:
            model_path = os.path.join(self.model_dir, f"{symbol}_ensemble.pkl")
            scaler_path = os.path.join(self.model_dir, f"{symbol}_scaler.pkl")
            selector_path = os.path.join(self.model_dir, f"{symbol}_selector.pkl")
            metrics_path = os.path.join(self.model_dir, f"{symbol}_metrics.json")
            
            if os.path.exists(model_path):
                # 加载已有模型
                try:
                    self.models[symbol] = joblib.load(model_path)
                    self.scalers[symbol] = joblib.load(scaler_path)
                    self.feature_selectors[symbol] = joblib.load(selector_path)
                    
                    # 加载性能指标
                    if os.path.exists(metrics_path):
                        with open(metrics_path, 'r') as f:
                            self.model_metrics[symbol] = json.load(f)
                    
                    logger.info(f"加载 {symbol} 的已有模型")
                    logger.info(f"  模型性能: {self.model_metrics.get(symbol, {})}")
                except Exception as e:
                    logger.error(f"加载 {symbol} 模型失败: {e}")
                    self._train_model(symbol)
            else:
                # 训练新模型
                logger.info(f"训练 {symbol} 的新模型")
                self._train_model(symbol)
    
    def _load_data(self, symbol: str, limit: Optional[int] = None) -> pd.DataFrame:
        """
        加载历史数据（使用全量数据）
        """
        # 尝试不同的数据格式
        file_patterns = [
            f"{symbol}_1d.csv",
            f"{symbol}.csv",
            f"{symbol}_1h.csv" if self.use_hourly_data else None
        ]
        
        for pattern in file_patterns:
            if pattern is None:
                continue
                
            file_path = os.path.join(self.data_dir, pattern)
            if os.path.exists(file_path):
                df = pd.read_csv(file_path)
                
                # 标准化列名
                df.columns = [col.lower() for col in df.columns]
                
                # 确保有日期列
                if 'date' in df.columns:
                    df['date'] = pd.to_datetime(df['date'])
                    df.set_index('date', inplace=True)
                elif 'timestamp' in df.columns:
                    df['timestamp'] = pd.to_datetime(df['timestamp'])
                    df.set_index('timestamp', inplace=True)
                
                # 按时间排序
                df.sort_index(inplace=True)
                
                # 限制数据量（如果需要）
                if limit:
                    df = df.tail(limit)
                
                logger.info(f"加载 {symbol} 数据: {len(df)} 条记录, 从 {df.index[0]} 到 {df.index[-1]}")
                
                return df
        
        logger.warning(f"未找到 {symbol} 的数据文件")
        return pd.DataFrame()
    
    def _create_advanced_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        创建高级特征（100+特征）
        """
        features = pd.DataFrame(index=df.index)
        
        # 基础价格特征
        features['returns'] = df['close'].pct_change()
        features['log_returns'] = np.log(df['close'] / df['close'].shift(1))
        features['price_change'] = df['close'] - df['close'].shift(1)
        
        # 价格位置特征
        features['hl_ratio'] = (df['high'] - df['low']) / df['close']
        features['hc_ratio'] = (df['high'] - df['close']) / df['close']
        features['cl_ratio'] = (df['close'] - df['low']) / df['close']
        features['oc_ratio'] = (df['close'] - df['open']) / df['open']
        
        # 成交量特征
        features['volume_ratio'] = df['volume'] / df['volume'].rolling(20).mean()
        features['volume_change'] = df['volume'].pct_change()
        features['volume_price'] = df['volume'] * df['close']
        features['volume_price_ratio'] = features['volume_price'] / features['volume_price'].rolling(20).mean()
        
        # 移动平均特征
        for period in [5, 10, 20, 30, 50, 100, 200]:
            features[f'ma_{period}'] = df['close'].rolling(period).mean()
            features[f'ma_ratio_{period}'] = df['close'] / features[f'ma_{period}']
            features[f'ma_diff_{period}'] = df['close'] - features[f'ma_{period}']
            
            # 成交量移动平均
            features[f'vma_{period}'] = df['volume'].rolling(period).mean()
            features[f'vma_ratio_{period}'] = df['volume'] / features[f'vma_{period}']
        
        # 技术指标
        # RSI
        for period in [7, 14, 21]:
            features[f'rsi_{period}'] = self._calculate_rsi(df['close'], period)
        
        # MACD
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        features['macd'] = exp1 - exp2
        features['macd_signal'] = features['macd'].ewm(span=9, adjust=False).mean()
        features['macd_diff'] = features['macd'] - features['macd_signal']
        
        # 布林带
        for period in [10, 20, 30]:
            bb_mean = df['close'].rolling(period).mean()
            bb_std = df['close'].rolling(period).std()
            features[f'bb_upper_{period}'] = bb_mean + (bb_std * 2)
            features[f'bb_lower_{period}'] = bb_mean - (bb_std * 2)
            features[f'bb_width_{period}'] = features[f'bb_upper_{period}'] - features[f'bb_lower_{period}']
            features[f'bb_position_{period}'] = (df['close'] - features[f'bb_lower_{period}']) / features[f'bb_width_{period}']
        
        # ATR (Average True Range)
        for period in [7, 14, 21]:
            features[f'atr_{period}'] = self._calculate_atr(df, period)
            features[f'atr_ratio_{period}'] = features[f'atr_{period}'] / df['close']
        
        # 波动率特征
        for period in [5, 10, 20, 30]:
            features[f'volatility_{period}'] = df['close'].pct_change().rolling(period).std()
            features[f'volatility_ratio_{period}'] = features[f'volatility_{period}'] / features[f'volatility_{period}'].rolling(50).mean()
            
            # Parkinson波动率
            features[f'parkinson_vol_{period}'] = np.sqrt(
                (1/(4*np.log(2))) * ((np.log(df['high']/df['low'])**2).rolling(period).mean())
            )
        
        # 市场微结构特征
        features['spread'] = (df['high'] - df['low']) / df['close']
        features['spread_ma'] = features['spread'].rolling(20).mean()
        features['spread_std'] = features['spread'].rolling(20).std()
        
        # 动量特征
        for period in [3, 5, 10, 20]:
            features[f'momentum_{period}'] = df['close'] / df['close'].shift(period) - 1
            features[f'momentum_ma_{period}'] = features[f'momentum_{period}'].rolling(10).mean()
        
        # 成交量加权平均价格（VWAP）
        features['vwap'] = (df['volume'] * (df['high'] + df['low'] + df['close']) / 3).cumsum() / df['volume'].cumsum()
        features['vwap_ratio'] = df['close'] / features['vwap']
        
        # 累积指标
        features['cum_returns'] = (1 + features['returns']).cumprod()
        features['cum_volume'] = df['volume'].cumsum()
        
        # 滞后特征
        for i in range(1, 11):
            features[f'returns_lag_{i}'] = features['returns'].shift(i)
            features[f'volume_lag_{i}'] = features['volume_ratio'].shift(i)
        
        # 滚动统计特征
        for window in [5, 10, 20, 50]:
            # 收益率统计
            features[f'returns_mean_{window}'] = features['returns'].rolling(window).mean()
            features[f'returns_std_{window}'] = features['returns'].rolling(window).std()
            features[f'returns_skew_{window}'] = features['returns'].rolling(window).skew()
            features[f'returns_kurt_{window}'] = features['returns'].rolling(window).kurt()
            features[f'returns_max_{window}'] = features['returns'].rolling(window).max()
            features[f'returns_min_{window}'] = features['returns'].rolling(window).min()
            
            # 价格统计
            features[f'price_max_{window}'] = df['high'].rolling(window).max()
            features[f'price_min_{window}'] = df['low'].rolling(window).min()
            features[f'price_range_{window}'] = features[f'price_max_{window}'] - features[f'price_min_{window}']
            
        # 时间特征（如果使用小时数据）
        if self.use_hourly_data:
            features['hour'] = df.index.hour
            features['day_of_week'] = df.index.dayofweek
            features['day_of_month'] = df.index.day
            features['month'] = df.index.month
            features['hour_sin'] = np.sin(2 * np.pi * features['hour'] / 24)
            features['hour_cos'] = np.cos(2 * np.pi * features['hour'] / 24)
        
        return features
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """计算RSI"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算ATR"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        return atr
    
    def _create_dynamic_labels(self, df: pd.DataFrame, features: pd.DataFrame) -> pd.Series:
        """
        创建动态标签（基于波动率调整阈值）
        """
        future_returns = df['close'].shift(-self.config['prediction_horizon']) / df['close'] - 1
        
        if self.config['dynamic_threshold']:
            # 计算滚动波动率
            volatility = df['close'].pct_change().rolling(20).std()
            
            # 动态阈值：基于波动率调整
            up_threshold = volatility * 0.5  # 上涨阈值
            down_threshold = -volatility * 0.5  # 下跌阈值
            
            # 或者使用百分位数
            threshold_percentile = self.config['threshold_percentile']
            up_threshold = future_returns.rolling(100).quantile(threshold_percentile/100)
            down_threshold = future_returns.rolling(100).quantile((100-threshold_percentile)/100)
            
            labels = pd.Series(index=df.index, dtype=int)
            labels[future_returns < down_threshold] = 0  # 下跌
            labels[future_returns > up_threshold] = 2    # 上涨
            labels[(future_returns >= down_threshold) & (future_returns <= up_threshold)] = 1  # 横盘
        else:
            # 固定阈值
            threshold = 0.005  # 0.5%
            labels = pd.Series(index=df.index, dtype=int)
            labels[future_returns < -threshold] = 0  # 下跌
            labels[future_returns > threshold] = 2    # 上涨
            labels[(future_returns >= -threshold) & (future_returns <= threshold)] = 1  # 横盘
        
        return labels
    
    def _train_model(self, symbol: str):
        """
        训练集成模型
        """
        # 加载数据
        df = self._load_data(symbol)
        if len(df) < self.config['min_data_points']:
            logger.warning(f"{symbol} 数据不足，跳过训练")
            return
        
        # 创建特征
        features = self._create_advanced_features(df)
        
        # 创建标签
        labels = self._create_dynamic_labels(df, features)
        
        # 删除NaN
        valid_idx = ~(features.isna().any(axis=1) | labels.isna())
        features = features[valid_idx]
        labels = labels[valid_idx]
        
        if len(features) < self.config['min_data_points']:
            logger.warning(f"{symbol} 有效数据不足")
            return
        
        # 特征选择
        logger.info(f"原始特征数量: {features.shape[1]}")
        
        # 使用多种特征选择方法
        if self.config['n_features'] < features.shape[1]:
            # 方法1：SelectKBest
            selector = SelectKBest(f_classif, k=min(self.config['n_features'], features.shape[1]))
            features_selected = selector.fit_transform(features, labels)
            selected_features = features.columns[selector.get_support()].tolist()
            
            # 保存特征选择器
            self.feature_selectors[symbol] = {
                'selector': selector,
                'features': selected_features
            }
            
            features = pd.DataFrame(features_selected, columns=selected_features, index=features.index)
        
        logger.info(f"选择后特征数量: {features.shape[1]}")
        
        # 时间序列分割（不能随机分割）
        split_idx = int(len(features) * (1 - self.config['test_size']))
        X_train = features[:split_idx]
        X_test = features[split_idx:]
        y_train = labels[:split_idx]
        y_test = labels[split_idx:]
        
        # 数据缩放
        scaler = RobustScaler()  # 对异常值更鲁棒
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        self.scalers[symbol] = scaler
        
        # 训练多个模型
        models = {}
        scores = {}
        
        # 1. XGBoost
        if XGBOOST_AVAILABLE and 'xgboost' in self.config['models_to_use']:
            logger.info(f"训练 {symbol} 的XGBoost模型...")
            xgb_model = xgb.XGBClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.01,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=42,
                n_jobs=-1,
                eval_metric='mlogloss'
            )
            xgb_model.fit(X_train_scaled, y_train)
            models['xgboost'] = xgb_model
            scores['xgboost'] = xgb_model.score(X_test_scaled, y_test)
            logger.info(f"XGBoost准确率: {scores['xgboost']:.4f}")
        
        # 2. LightGBM
        if LIGHTGBM_AVAILABLE and 'lightgbm' in self.config['models_to_use']:
            logger.info(f"训练 {symbol} 的LightGBM模型...")
            lgb_model = lgb.LGBMClassifier(
                n_estimators=200,
                num_leaves=31,
                learning_rate=0.01,
                feature_fraction=0.8,
                bagging_fraction=0.8,
                bagging_freq=5,
                random_state=42,
                n_jobs=-1
            )
            lgb_model.fit(X_train_scaled, y_train)
            models['lightgbm'] = lgb_model
            scores['lightgbm'] = lgb_model.score(X_test_scaled, y_test)
            logger.info(f"LightGBM准确率: {scores['lightgbm']:.4f}")
        
        # 3. 随机森林
        if 'rf' in self.config['models_to_use']:
            logger.info(f"训练 {symbol} 的随机森林模型...")
            rf_model = RandomForestClassifier(
                n_estimators=200,
                max_depth=10,
                min_samples_split=5,
                min_samples_leaf=2,
                random_state=42,
                n_jobs=-1
            )
            rf_model.fit(X_train_scaled, y_train)
            models['rf'] = rf_model
            scores['rf'] = rf_model.score(X_test_scaled, y_test)
            logger.info(f"随机森林准确率: {scores['rf']:.4f}")
        
        # 4. 梯度提升
        if 'gb' in self.config['models_to_use']:
            logger.info(f"训练 {symbol} 的梯度提升模型...")
            gb_model = GradientBoostingClassifier(
                n_estimators=100,
                learning_rate=0.05,
                max_depth=5,
                random_state=42
            )
            gb_model.fit(X_train_scaled, y_train)
            models['gb'] = gb_model
            scores['gb'] = gb_model.score(X_test_scaled, y_test)
            logger.info(f"梯度提升准确率: {scores['gb']:.4f}")
        
        # 保存集成模型
        self.models[symbol] = models
        
        # 计算集成预测的性能
        ensemble_pred = self._ensemble_predict(models, X_test_scaled)
        ensemble_score = accuracy_score(y_test, ensemble_pred)
        
        # 计算详细指标
        precision = precision_score(y_test, ensemble_pred, average='weighted', zero_division=0)
        recall = recall_score(y_test, ensemble_pred, average='weighted', zero_division=0)
        f1 = f1_score(y_test, ensemble_pred, average='weighted', zero_division=0)
        
        # 保存性能指标
        self.model_metrics[symbol] = {
            'accuracy': float(ensemble_score),
            'precision': float(precision),
            'recall': float(recall),
            'f1_score': float(f1),
            'individual_scores': {k: float(v) for k, v in scores.items()},
            'train_samples': len(X_train),
            'test_samples': len(X_test),
            'features_used': len(selected_features) if 'selected_features' in locals() else features.shape[1],
            'training_date': datetime.now().isoformat()
        }
        
        logger.info(f"{symbol} 集成模型性能 - 准确率: {ensemble_score:.4f}, F1: {f1:.4f}")
        
        # 特征重要性（如果可用）
        if 'xgboost' in models:
            feature_importance = models['xgboost'].feature_importances_
            feature_names = selected_features if 'selected_features' in locals() else features.columns
            self.feature_importance[symbol] = dict(zip(feature_names, feature_importance))
            
            # 显示前10个重要特征
            top_features = sorted(self.feature_importance[symbol].items(), key=lambda x: x[1], reverse=True)[:10]
            logger.info(f"{symbol} 前10个重要特征:")
            for feat, importance in top_features:
                logger.info(f"  - {feat}: {importance:.4f}")
        
        # 保存模型
        self._save_models(symbol)
    
    def _ensemble_predict(self, models: Dict, X: np.ndarray) -> np.ndarray:
        """
        集成预测（投票法）
        """
        predictions = []
        weights = {
            'xgboost': 0.35,
            'lightgbm': 0.35,
            'rf': 0.2,
            'gb': 0.1
        }
        
        for name, model in models.items():
            pred = model.predict(X)
            weight = weights.get(name, 1.0 / len(models))
            predictions.append(pred * weight)
        
        # 加权平均后取整
        ensemble_pred = np.sum(predictions, axis=0)
        return np.round(ensemble_pred).astype(int)
    
    def _ensemble_predict_proba(self, models: Dict, X: np.ndarray) -> np.ndarray:
        """
        集成预测概率
        """
        probabilities = []
        weights = {
            'xgboost': 0.35,
            'lightgbm': 0.35,
            'rf': 0.2,
            'gb': 0.1
        }
        
        for name, model in models.items():
            proba = model.predict_proba(X)
            weight = weights.get(name, 1.0 / len(models))
            probabilities.append(proba * weight)
        
        # 加权平均
        return np.sum(probabilities, axis=0)
    
    def _save_models(self, symbol: str):
        """保存模型和相关数据"""
        try:
            # 保存集成模型
            model_path = os.path.join(self.model_dir, f"{symbol}_ensemble.pkl")
            joblib.dump(self.models[symbol], model_path)
            
            # 保存缩放器
            scaler_path = os.path.join(self.model_dir, f"{symbol}_scaler.pkl")
            joblib.dump(self.scalers[symbol], scaler_path)
            
            # 保存特征选择器
            if symbol in self.feature_selectors:
                selector_path = os.path.join(self.model_dir, f"{symbol}_selector.pkl")
                joblib.dump(self.feature_selectors[symbol], selector_path)
            
            # 保存性能指标
            metrics_path = os.path.join(self.model_dir, f"{symbol}_metrics.json")
            with open(metrics_path, 'w') as f:
                json.dump(self.model_metrics[symbol], f, indent=2)
            
            # 保存特征重要性
            if symbol in self.feature_importance:
                importance_path = os.path.join(self.model_dir, f"{symbol}_importance.json")
                with open(importance_path, 'w') as f:
                    json.dump(self.feature_importance[symbol], f, indent=2)
            
            logger.info(f"模型已保存: {symbol}")
        except Exception as e:
            logger.error(f"保存模型失败 {symbol}: {e}")
    
    def generate_signal(self, symbol: str) -> Optional[Dict]:
        """
        生成交易信号
        """
        if symbol not in self.models:
            logger.warning(f"{symbol} 没有可用模型")
            return None
        
        try:
            # 加载最新数据
            df = self._load_data(symbol, limit=500)  # 只需要最近的数据来生成信号
            if len(df) < 100:
                return None
            
            # 创建特征
            features = self._create_advanced_features(df)
            
            # 特征选择
            if symbol in self.feature_selectors:
                selector_info = self.feature_selectors[symbol]
                features = features[selector_info['features']]
            
            # 获取最新的特征（去掉NaN）
            latest_features = features.dropna().iloc[-1:].values
            
            # 缩放
            latest_features_scaled = self.scalers[symbol].transform(latest_features)
            
            # 集成预测
            models = self.models[symbol]
            prediction = self._ensemble_predict(models, latest_features_scaled)[0]
            probabilities = self._ensemble_predict_proba(models, latest_features_scaled)[0]
            
            # 映射预测到交易信号
            signal_map = {0: 'SELL', 1: 'HOLD', 2: 'BUY'}
            recommendation = signal_map[prediction]
            
            # 计算置信度（最高概率）
            confidence = float(np.max(probabilities))
            
            # 风险评估
            risk_score = 1.0 - confidence
            volatility = float(df['close'].pct_change().rolling(20).std().iloc[-1])
            
            if volatility > 0.05:
                risk_level = 'HIGH'
            elif volatility > 0.02:
                risk_level = 'MEDIUM'
            else:
                risk_level = 'LOW'
            
            # 计算技术指标（用于参考）
            current_price = float(df['close'].iloc[-1])
            ma_20 = float(df['close'].rolling(20).mean().iloc[-1])
            rsi = float(self._calculate_rsi(df['close']).iloc[-1])
            
            signal = {
                'symbol': symbol,
                'timestamp': datetime.now().isoformat(),
                'recommendation': recommendation,
                'confidence': confidence,
                'price': current_price,
                'volume': float(df['volume'].iloc[-1]),
                'ai_prediction': {
                    'direction': recommendation,
                    'probability_down': float(probabilities[0]),
                    'probability_hold': float(probabilities[1]),
                    'probability_up': float(probabilities[2]),
                    'model_type': 'ENSEMBLE',
                    'models_used': list(models.keys())
                },
                'technical_indicators': {
                    'rsi': rsi,
                    'ma_20': ma_20,
                    'price_to_ma20': current_price / ma_20,
                    'volatility': volatility
                },
                'risk_metrics': {
                    'risk_score': risk_score,
                    'risk_level': risk_level,
                    'volatility': volatility,
                    'suggested_position_size': max(0.1, min(1.0, 1.0 - risk_score))
                },
                'model_metrics': self.model_metrics.get(symbol, {}),
                'signal_strength': confidence,
                'reasons': self._generate_reasons(recommendation, confidence, rsi, current_price/ma_20)
            }
            
            return signal
            
        except Exception as e:
            logger.error(f"生成信号失败 {symbol}: {e}")
            return None
    
    def _generate_reasons(self, recommendation: str, confidence: float, rsi: float, price_to_ma: float) -> List[str]:
        """生成信号原因"""
        reasons = []
        
        if confidence > 0.7:
            reasons.append(f"高置信度信号 ({confidence:.2%})")
        elif confidence > 0.6:
            reasons.append(f"中等置信度信号 ({confidence:.2%})")
        
        if recommendation == 'BUY':
            if rsi < 30:
                reasons.append(f"RSI超卖 ({rsi:.1f})")
            if price_to_ma < 0.98:
                reasons.append("价格低于MA20")
        elif recommendation == 'SELL':
            if rsi > 70:
                reasons.append(f"RSI超买 ({rsi:.1f})")
            if price_to_ma > 1.02:
                reasons.append("价格高于MA20")
        
        return reasons
    
    def backtest(self, symbol: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict:
        """
        回测策略
        """
        logger.info(f"开始回测 {symbol}")
        
        # 加载数据
        df = self._load_data(symbol)
        
        # 创建特征和标签
        features = self._create_advanced_features(df)
        labels = self._create_dynamic_labels(df, features)
        
        # 删除NaN
        valid_idx = ~(features.isna().any(axis=1) | labels.isna())
        features = features[valid_idx]
        labels = labels[valid_idx]
        df_valid = df[valid_idx]
        
        # 时间范围过滤
        if start_date:
            features = features[features.index >= start_date]
            labels = labels[labels.index >= start_date]
            df_valid = df_valid[df_valid.index >= start_date]
        if end_date:
            features = features[features.index <= end_date]
            labels = labels[labels.index <= end_date]
            df_valid = df_valid[df_valid.index <= end_date]
        
        # 特征选择
        if symbol in self.feature_selectors:
            selector_info = self.feature_selectors[symbol]
            features = features[selector_info['features']]
        
        # 缩放
        features_scaled = self.scalers[symbol].transform(features)
        
        # 预测
        if symbol in self.models:
            predictions = self._ensemble_predict(self.models[symbol], features_scaled)
            probabilities = self._ensemble_predict_proba(self.models[symbol], features_scaled)
        else:
            logger.error(f"没有可用的模型: {symbol}")
            return {}
        
        # 计算回测指标
        # 简单策略：买入信号时买入，卖出信号时卖出
        positions = pd.Series(index=df_valid.index, dtype=float)
        positions[predictions == 2] = 1.0   # 买入
        positions[predictions == 0] = -1.0  # 卖出
        positions[predictions == 1] = 0.0   # 持有（不操作）
        positions = positions.fillna(0)
        
        # 计算收益
        returns = df_valid['close'].pct_change()
        strategy_returns = positions.shift(1) * returns
        
        # 累积收益
        cum_returns = (1 + returns).cumprod()
        cum_strategy_returns = (1 + strategy_returns).cumprod()
        
        # 计算指标
        total_return = float(cum_strategy_returns.iloc[-1] - 1)
        buy_hold_return = float(cum_returns.iloc[-1] - 1)
        
        # 夏普比率
        sharpe_ratio = strategy_returns.mean() / strategy_returns.std() * np.sqrt(252) if strategy_returns.std() > 0 else 0
        
        # 最大回撤
        rolling_max = cum_strategy_returns.expanding().max()
        drawdown = (cum_strategy_returns - rolling_max) / rolling_max
        max_drawdown = float(drawdown.min())
        
        # 胜率
        winning_trades = (strategy_returns > 0).sum()
        losing_trades = (strategy_returns < 0).sum()
        total_trades = winning_trades + losing_trades
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        backtest_results = {
            'symbol': symbol,
            'period': f"{df_valid.index[0]} to {df_valid.index[-1]}",
            'total_return': total_return,
            'buy_hold_return': buy_hold_return,
            'sharpe_ratio': float(sharpe_ratio),
            'max_drawdown': max_drawdown,
            'win_rate': float(win_rate),
            'total_trades': int(total_trades),
            'winning_trades': int(winning_trades),
            'losing_trades': int(losing_trades),
            'model_accuracy': self.model_metrics.get(symbol, {}).get('accuracy', 0)
        }
        
        self.backtest_results[symbol] = backtest_results
        
        logger.info(f"{symbol} 回测结果:")
        logger.info(f"  策略收益: {total_return:.2%}")
        logger.info(f"  买入持有收益: {buy_hold_return:.2%}")
        logger.info(f"  夏普比率: {sharpe_ratio:.2f}")
        logger.info(f"  最大回撤: {max_drawdown:.2%}")
        logger.info(f"  胜率: {win_rate:.2%}")
        
        return backtest_results
    
    def retrain_all_models(self):
        """重新训练所有模型"""
        logger.info("开始重新训练所有模型...")
        for symbol in self.symbols:
            logger.info(f"重新训练 {symbol}")
            self._train_model(symbol)
        logger.info("所有模型训练完成")
    
    def get_all_signals(self) -> Dict:
        """获取所有币种的信号"""
        signals = {}
        for symbol in self.symbols:
            signal = self.generate_signal(symbol)
            if signal:
                signals[symbol] = signal
        return signals


class ProductionMLHTTPHandler(BaseHTTPRequestHandler):
    """HTTP API处理器"""
    
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            response = {
                'status': 'ok',
                'service': 'production-ml-strategy',
                'models_loaded': len(self.server.analyzer.models),
                'symbols': self.server.analyzer.symbols,
                'timestamp': datetime.now().isoformat()
            }
            self.wfile.write(json.dumps(response).encode())
            
        elif self.path == '/signals':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            signals = self.server.analyzer.get_all_signals()
            response = {
                'status': 'success',
                'timestamp': datetime.now().isoformat(),
                'data': signals
            }
            self.wfile.write(json.dumps(response).encode())
            
        elif self.path == '/metrics':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            response = {
                'status': 'success',
                'model_metrics': self.server.analyzer.model_metrics,
                'backtest_results': self.server.analyzer.backtest_results
            }
            self.wfile.write(json.dumps(response).encode())
            
        elif self.path == '/retrain':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            # 在后台线程中重新训练
            threading.Thread(target=self.server.analyzer.retrain_all_models).start()
            
            response = {
                'status': 'success',
                'message': 'Retraining started in background'
            }
            self.wfile.write(json.dumps(response).encode())
            
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass  # 禁用请求日志


def start_http_server(analyzer, port=8091):
    """启动HTTP服务器"""
    try:
        httpd = HTTPServer(('', port), ProductionMLHTTPHandler)
        httpd.analyzer = analyzer
        logger.info(f"HTTP服务器启动在端口 {port}")
        httpd.serve_forever()
    except Exception as e:
        logger.error(f"HTTP服务器错误: {e}")


def main():
    """主函数"""
    print("=" * 60)
    print("🚀 生产级ML策略分析器")
    print("=" * 60)
    
    # 创建分析器
    print("🔧 初始化生产级ML分析器...")
    analyzer = ProductionMLStrategy()
    
    # 运行回测
    print("\n📊 运行回测...")
    for symbol in analyzer.symbols[:2]:  # 只回测前两个
        analyzer.backtest(symbol)
    
    # 启动HTTP服务器
    http_thread = threading.Thread(
        target=start_http_server,
        args=(analyzer, 8091),
        daemon=True
    )
    http_thread.start()
    
    print("\n✅ 生产级ML策略系统启动成功！")
    print(f"📡 HTTP API: http://localhost:8091")
    print(f"📊 监控交易对: {', '.join(analyzer.symbols)}")
    print(f"🧠 已加载模型: {len(analyzer.models)} 个")
    print(f"💾 模型目录: {analyzer.model_dir}")
    print("\n📌 API端点:")
    print("  GET /health   - 健康检查")
    print("  GET /signals  - 获取所有信号")
    print("  GET /metrics  - 查看模型指标")
    print("  GET /retrain  - 重新训练模型")
    
    # 显示初始信号
    print("\n📈 生成初始信号...")
    for symbol in analyzer.symbols:
        signal = analyzer.generate_signal(symbol)
        if signal:
            print(f"{symbol}: {signal['recommendation']} (置信度: {signal['confidence']:.2%}, 风险: {signal['risk_metrics']['risk_level']})")
    
    # 保持运行
    try:
        while True:
            time.sleep(60)
            # 每分钟生成一次信号
            for symbol in analyzer.symbols:
                analyzer.generate_signal(symbol)
    except KeyboardInterrupt:
        print("\n正在关闭...")
        

if __name__ == "__main__":
    main()