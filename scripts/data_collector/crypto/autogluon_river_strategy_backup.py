"""
AutoGluon + River 加密货币交易策略

- AutoGluon: 离线批量训练强大的集成模型
- River: 在线增量学习，实时适应市场变化
- 专为i5-7700 + 16GB + GTX 1060配置优化

核心功能:
1. AutoGluon自动机器学习（每日UTC 12:00重训练）
2. River在线学习（实时更新模型参数）
3. 智能信号融合（离线+在线预测结合）
4. 自动数据更新和特征工程
"""

import os
import sys
import pandas as pd
import numpy as np
import json
import pickle
import warnings
import threading
import asyncio
import websockets
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any
from loguru import logger
import time

warnings.filterwarnings('ignore')

# 配置loguru日志输出到文件
logger.remove()  # 移除默认处理器
logger.add(sys.stderr, level="INFO")  # 控制台输出
logger.add("/tmp/autogluon_river.log",
           rotation="1 day",  # 每天轮转
           retention="7 days",  # 保留7天
           level="DEBUG",
           format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")

# AutoGluon
try:
    from autogluon.tabular import TabularDataset, TabularPredictor
    AUTOGLUON_AVAILABLE = True
    logger.info("AutoGluon可用")
except ImportError:
    AUTOGLUON_AVAILABLE = False
    logger.error("AutoGluon未安装，请运行: pip install autogluon.tabular")

# River在线学习
try:
    import river
    from river import compose, linear_model, preprocessing, metrics, ensemble
    RIVER_AVAILABLE = True
    logger.info("River可用")
except ImportError:
    RIVER_AVAILABLE = False
    logger.error("River未安装，请运行: pip install river")


class AutoGluonRiverStrategy:
    """
    AutoGluon + River 集成策略
    结合离线训练的强大模型和在线学习的适应性
    """
    
    def __init__(self, use_hourly_data: bool = True):
        """
        初始化策略

        Args:
            use_hourly_data: 是否使用小时数据
        """
        self.use_hourly_data = use_hourly_data
        self.symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'SUIUSDT', 'ADAUSDT', 'DOGEUSDT']

        # 目录设置
        self.base_dir = os.path.expanduser("~/.qlib")
        self.data_dir = os.path.join(self.base_dir, "binance_hourly_data" if use_hourly_data else "binance_data")
        self.model_dir = os.path.join(self.base_dir, "autogluon_river_models")
        self.river_dir = os.path.join(self.base_dir, "river_models")

        # 创建目录
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.model_dir, exist_ok=True)
        os.makedirs(self.river_dir, exist_ok=True)

        # 模型容器
        self.autogluon_models = {}  # AutoGluon离线模型
        self.river_models = {}      # River在线模型
        self.feature_columns = {}   # 特征列名

        # 配置参数
        self.min_confidence = float(os.environ.get('ML_MIN_CONFIDENCE', '0.55'))  # 55%，超过随机50%
        self.dead_zone = float(os.environ.get('ML_DEAD_ZONE', '0.005'))
        self.max_memory_mb = int(os.environ.get('MAX_MEMORY_MB', '8192'))  # 最大内存限制8GB
        self.lookforward = int(os.environ.get('ML_LOOKFORWARD', '24'))  # 统一的预测窗口
        self.warmup = 50  # 特征计算预热期

        # 特征列元数据路径
        self._feature_meta_path = os.path.join(self.model_dir, "_feature_columns.json")

        # 训练控制
        self._training_lock = threading.RLock()
        self._river_lock = threading.RLock()  # River模型并发锁
        self._last_retrain_date = None
        self.enable_auto_retrain = True
        
        logger.info("AutoGluon+River策略初始化完成")

        # 加载特征列配置
        self._load_feature_columns()

        # 初始化模型
        self._initialize_models()
    
    def _load_feature_columns(self):
        """加载特征列配置"""
        if os.path.exists(self._feature_meta_path):
            try:
                with open(self._feature_meta_path, 'r') as f:
                    self.feature_columns = json.load(f)
                logger.info(f"已加载特征列配置: {len(self.feature_columns)}个模型")
            except Exception as e:
                logger.warning(f"特征列加载失败: {e}")

    def _save_feature_columns(self):
        """保存特征列配置"""
        try:
            with open(self._feature_meta_path, 'w') as f:
                json.dump(self.feature_columns, f)
            logger.debug("特征列配置已保存")
        except Exception as e:
            logger.warning(f"特征列保存失败: {e}")

    def _initialize_models(self):
        """初始化所有模型"""
        for symbol in self.symbols:
            # 加载或创建AutoGluon模型
            self._load_autogluon_model(symbol)

            # 初始化River在线模型
            self._initialize_river_model(symbol)
    
    def _load_autogluon_model(self, symbol: str):
        """加载AutoGluon模型"""
        model_path = os.path.join(self.model_dir, f"{symbol}_autogluon")
        
        if os.path.exists(model_path):
            try:
                self.autogluon_models[symbol] = TabularPredictor.load(model_path)
                logger.info(f"已加载 {symbol} AutoGluon模型")
            except Exception as e:
                logger.warning(f"加载 {symbol} AutoGluon模型失败: {e}")
                self.autogluon_models[symbol] = None
        else:
            self.autogluon_models[symbol] = None
            logger.info(f"{symbol} AutoGluon模型不存在，需要训练")
    
    def _initialize_river_model(self, symbol: str):
        """初始化River在线学习模型"""
        river_path = os.path.join(self.river_dir, f"{symbol}_river.pkl")
        
        if os.path.exists(river_path):
            try:
                with open(river_path, 'rb') as f:
                    self.river_models[symbol] = pickle.load(f)
                logger.info(f"已加载 {symbol} River模型")
            except Exception as e:
                logger.warning(f"加载 {symbol} River模型失败: {e}")
                self._create_new_river_model(symbol)
        else:
            self._create_new_river_model(symbol)
    
    def _create_new_river_model(self, symbol: str):
        """创建新的River在线模型"""
        # 组合模型：标准化 + 装袋分类器
        from river import tree
        model = compose.Pipeline(
            preprocessing.StandardScaler(),
            ensemble.BaggingClassifier(
                model=tree.HoeffdingTreeClassifier(),
                n_models=8,  # 减少模型数量提升速度
                seed=42
            )
        )

        self.river_models[symbol] = {
            'model': model,
            'accuracy': metrics.Accuracy(),
            'samples_processed': 0,
            'last_updated': datetime.utcnow(),
            'last_train_ts': None  # 记录最后训练的时间戳，防止重复学习
        }
        
        logger.info(f"创建新的 {symbol} River在线模型")
    
    def _load_data(self, symbol: str) -> pd.DataFrame:
        """加载并预处理数据"""
        try:
            file_path = os.path.join(self.data_dir, f"{symbol}.csv")
            
            if not os.path.exists(file_path):
                logger.warning(f"数据文件不存在: {file_path}")
                if self._download_data(symbol):
                    logger.info(f"成功下载 {symbol} 数据")
                else:
                    logger.error(f"下载 {symbol} 数据失败")
                    return pd.DataFrame()
            
            # 读取数据
            df = pd.read_csv(file_path)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
            
            # 尝试获取最新数据（增量更新）
            self._update_latest_data(symbol, df, file_path)
            
            return df
            
        except Exception as e:
            logger.error(f"加载 {symbol} 数据失败: {e}")
            return pd.DataFrame()
    
    def _download_data(self, symbol: str) -> bool:
        """下载历史数据"""
        try:
            logger.info(f"开始下载 {symbol} 数据...")
            
            # 时间范围
            end_date = datetime.now()
            start_date = datetime(2021, 1, 1)
            
            # 特殊处理新币上线时间
            if symbol == 'SUIUSDT':
                start_date = datetime(2023, 5, 3)
            
            url = "https://api.binance.com/api/v3/klines"
            all_data = []
            current_start = start_date
            
            while current_start < end_date:
                current_end = min(current_start + timedelta(days=500), end_date)
                
                params = {
                    'symbol': symbol,
                    'interval': '1h' if self.use_hourly_data else '1d',
                    'startTime': int(current_start.timestamp() * 1000),
                    'endTime': int(current_end.timestamp() * 1000),
                    'limit': 1000
                }
                
                response = requests.get(url, params=params, timeout=30)
                if response.status_code == 200:
                    data = response.json()
                    if data:
                        all_data.extend(data)
                        current_start = datetime.fromtimestamp(data[-1][0]/1000) + timedelta(hours=1)
                    else:
                        break
                else:
                    break
                
                time.sleep(0.1)  # 避免频率限制
            
            if not all_data:
                return False
            
            # 转换为DataFrame
            df = pd.DataFrame(all_data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df[['date', 'open', 'high', 'low', 'close', 'volume']]
            
            # 数据类型转换
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col])
            
            # 保存数据
            save_path = os.path.join(self.data_dir, f"{symbol}.csv")
            df.to_csv(save_path, index=False)
            
            logger.info(f"✓ {symbol} 下载完成，共 {len(df)} 条记录")
            return True
            
        except Exception as e:
            logger.error(f"下载 {symbol} 数据失败: {e}")
            return False
    
    def _update_latest_data(self, symbol: str, df: pd.DataFrame, file_path: str):
        """增量更新最新数据"""
        try:
            if len(df) == 0:
                return
            
            last_date = df['date'].max()
            hours_ago = (datetime.now() - last_date).total_seconds() / 3600
            
            # 如果数据超过2小时，更新最新数据
            if hours_ago > 2:
                url = "https://api.binance.com/api/v3/klines"
                params = {
                    'symbol': symbol,
                    'interval': '1h' if self.use_hourly_data else '1d',
                    'limit': min(int(hours_ago) + 10, 100)
                }
                
                response = requests.get(url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if data:
                        new_df = pd.DataFrame(data, columns=[
                            'timestamp', 'open', 'high', 'low', 'close', 'volume',
                            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                            'taker_buy_quote', 'ignore'
                        ])
                        new_df['date'] = pd.to_datetime(new_df['timestamp'], unit='ms')
                        new_df = new_df[['date', 'open', 'high', 'low', 'close', 'volume']]
                        
                        for col in ['open', 'high', 'low', 'close', 'volume']:
                            new_df[col] = pd.to_numeric(new_df[col])
                        
                        # 合并数据
                        combined_df = pd.concat([df, new_df], ignore_index=True)
                        combined_df = combined_df.drop_duplicates(subset=['date'], keep='last')
                        combined_df = combined_df.sort_values('date').reset_index(drop=True)
                        
                        # 保存更新的数据
                        combined_df.to_csv(file_path, index=False)
                        logger.debug(f"{symbol} 数据已更新到 {combined_df['date'].max()}")
        
        except Exception as e:
            logger.warning(f"更新 {symbol} 最新数据失败: {e}")
    
    def _create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """创建技术分析特征"""
        features = pd.DataFrame()
        
        # 基础价格特征
        features['returns'] = df['close'].pct_change()
        features['log_returns'] = np.log(df['close'] / df['close'].shift(1))
        features['price_change'] = df['close'] - df['open']
        features['high_low_ratio'] = df['high'] / df['low']
        features['volume_change'] = df['volume'].pct_change()
        
        # 移动平均
        for period in [5, 10, 20, 50]:
            features[f'sma_{period}'] = df['close'].rolling(period).mean()
            features[f'price_to_sma_{period}'] = df['close'] / features[f'sma_{period}']
        
        # EMA
        for period in [12, 26]:
            features[f'ema_{period}'] = df['close'].ewm(span=period).mean()
        
        # MACD
        ema12 = df['close'].ewm(span=12).mean()
        ema26 = df['close'].ewm(span=26).mean()
        features['macd'] = ema12 - ema26
        features['macd_signal'] = features['macd'].ewm(span=9).mean()
        features['macd_histogram'] = features['macd'] - features['macd_signal']
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        features['rsi'] = 100 - (100 / (1 + rs))
        
        # 布林带
        sma20 = features['sma_20']
        std20 = df['close'].rolling(20).std()
        features['bb_upper'] = sma20 + (std20 * 2)
        features['bb_lower'] = sma20 - (std20 * 2)
        features['bb_position'] = (df['close'] - features['bb_lower']) / (features['bb_upper'] - features['bb_lower'])
        
        # 成交量指标
        features['volume_sma'] = df['volume'].rolling(20).mean()
        features['volume_ratio'] = df['volume'] / features['volume_sma']
        
        # 波动率
        features['volatility'] = df['close'].rolling(20).std()
        
        # 去除无限值和NaN
        features = features.replace([np.inf, -np.inf], np.nan)
        features = features.fillna(method='ffill').fillna(0)
        
        return features
    
    def _create_labels(self, df: pd.DataFrame) -> pd.Series:
        """创建标签（未来收益），防止标签泄漏"""
        close = df['close']
        future = close.shift(-self.lookforward)
        ret_fwd = future / close - 1

        # 动态阈值：基于滚动波动率
        vol = close.pct_change().rolling(48).std()
        dyn_threshold = (0.25 * vol).clip(lower=0.002)  # 最小0.2%阈值

        # 二分类：涨跌
        labels = (ret_fwd > dyn_threshold).astype(int)

        # 去掉尾部lookforward行（未来不可见，防止泄漏）
        labels = labels.iloc[:-self.lookforward]

        # 记录标签分布
        valid_labels = labels.dropna()
        if len(valid_labels) > 0:
            buy_ratio = valid_labels.sum() / len(valid_labels)
            logger.debug(f"标签分布 - BUY: {buy_ratio:.2%}, SELL: {1-buy_ratio:.2%}")

        return labels
    
    def train_autogluon_model(self, symbol: str) -> bool:
        """训练AutoGluon模型"""
        if not AUTOGLUON_AVAILABLE:
            logger.error("AutoGluon不可用")
            return False
        
        try:
            logger.info(f"开始训练 {symbol} AutoGluon模型...")
            
            # 加载数据
            df = self._load_data(symbol)
            if len(df) < 1000:
                logger.warning(f"{symbol} 数据不足，跳过训练")
                return False
            
            # 创建特征
            features = self._create_features(df)
            labels = self._create_labels(df)
            
            # 合并数据
            train_data = pd.concat([features, labels.rename('label')], axis=1)
            train_data = train_data.dropna()
            
            if len(train_data) < 500:
                logger.warning(f"{symbol} 有效训练数据不足")
                return False
            
            # 保存特征列名
            self.feature_columns[symbol] = list(features.columns)
            
            # 训练/测试分割
            split_idx = int(len(train_data) * 0.8)
            train_set = train_data.iloc[:split_idx]
            test_set = train_data.iloc[split_idx:]
            
            logger.info(f"{symbol} 训练集: {len(train_set)}, 测试集: {len(test_set)}")
            
            # AutoGluon配置（适合16GB内存）
            model_path = os.path.join(self.model_dir, f"{symbol}_autogluon")
            
            # 删除已存在的模型
            import shutil
            if os.path.exists(model_path):
                shutil.rmtree(model_path)
            
            # 支持配置二分类或三分类
            use_binary = os.environ.get('ML_USE_BINARY_CLASSIFICATION', 'true').lower() == 'true'
            problem_type = 'binary' if use_binary else 'multiclass'

            predictor = TabularPredictor(
                label='label',
                problem_type=problem_type,
                eval_metric='accuracy',
                path=model_path
            )
            
            # 训练配置（内存优化）
            predictor.fit(
                train_data=train_set,
                time_limit=180,  # 3分钟训练时间
                presets='medium_quality_faster_train',
                num_cpus=4,
                verbosity=1,
                hyperparameters={
                    'GBM': {},      # LightGBM
                    'CAT': {},      # CatBoost
                    'XGB': {},      # XGBoost
                    'RF': [{'n_estimators': 100}],  # RandomForest
                }
            )
            
            # 评估模型
            performance = predictor.evaluate(test_set, silent=True)
            accuracy = performance.get('accuracy', 0)
            
            # 保存模型
            self.autogluon_models[symbol] = predictor
            
            logger.info(f"✓ {symbol} AutoGluon训练完成，准确率: {accuracy:.2%}")
            return True
            
        except Exception as e:
            logger.error(f"{symbol} AutoGluon训练失败: {e}")
            return False
    
    def update_river_model(self, symbol: str, features: Dict, label: int):
        """更新River在线模型"""
        if not RIVER_AVAILABLE or symbol not in self.river_models:
            return
        
        try:
            model_info = self.river_models[symbol]
            model = model_info['model']
            accuracy_metric = model_info['accuracy']
            
            # 预测（在更新前）
            y_pred = model.predict_one(features)
            
            # 更新准确率指标
            accuracy_metric.update(label, y_pred)
            
            # 学习新样本
            model.learn_one(features, label)
            
            # 更新统计
            model_info['samples_processed'] += 1
            model_info['last_updated'] = datetime.now()
            model_info['current_accuracy'] = accuracy_metric.get()
            
            # 定期保存模型
            if model_info['samples_processed'] % 100 == 0:
                self._save_river_model(symbol)
                logger.debug(f"{symbol} River模型已处理 {model_info['samples_processed']} 样本，准确率: {accuracy_metric.get():.2%}")
            
        except Exception as e:
            logger.warning(f"更新 {symbol} River模型失败: {e}")
    
    def _save_river_model(self, symbol: str):
        """保存River模型"""
        try:
            river_path = os.path.join(self.river_dir, f"{symbol}_river.pkl")
            with open(river_path, 'wb') as f:
                pickle.dump(self.river_models[symbol], f)
        except Exception as e:
            logger.warning(f"保存 {symbol} River模型失败: {e}")
    
    def generate_signal(self, symbol: str) -> Optional[Dict]:
        """生成交易信号"""
        start_time = time.time()
        try:
            # 加载最新数据
            df = self._load_data(symbol)
            if len(df) < 100:
                return None
            
            # 创建特征
            features = self._create_features(df)
            latest_features = features.iloc[-1].to_dict()
            
            # 清理特征（移除无效值）
            latest_features = {k: v for k, v in latest_features.items() 
                             if not (np.isnan(v) or np.isinf(v))}
            
            predictions = []
            confidences = []
            
            # 1. AutoGluon预测
            if (symbol in self.autogluon_models and 
                self.autogluon_models[symbol] is not None and 
                AUTOGLUON_AVAILABLE):
                try:
                    feature_df = pd.DataFrame([latest_features])
                    # 确保特征顺序一致
                    if symbol in self.feature_columns:
                        feature_df = feature_df.reindex(columns=self.feature_columns[symbol], fill_value=0)
                    
                    pred_proba = self.autogluon_models[symbol].predict_proba(feature_df)
                    if hasattr(pred_proba, 'iloc'):
                        prob_positive = pred_proba.iloc[0, 1] if len(pred_proba.columns) > 1 else pred_proba.iloc[0]
                        prob_negative = pred_proba.iloc[0, 0] if len(pred_proba.columns) > 1 else (1 - prob_positive)
                    else:
                        prob_positive = pred_proba[1] if len(pred_proba) > 1 else pred_proba[0]
                        prob_negative = pred_proba[0] if len(pred_proba) > 1 else (1 - prob_positive)
                    
                    predictions.append(int(prob_positive > 0.5))
                    # 修复：取两个概率中的最大值作为置信度
                    confidences.append(max(prob_positive, prob_negative))
                    
                except Exception as e:
                    logger.debug(f"AutoGluon预测失败 {symbol}: {e}")
            
            # 2. River预测
            if (symbol in self.river_models and 
                RIVER_AVAILABLE and 
                self.river_models[symbol]['samples_processed'] > 100):
                try:
                    model = self.river_models[symbol]['model']
                    pred = model.predict_one(latest_features)
                    prob = model.predict_proba_one(latest_features)
                    
                    predictions.append(int(pred))
                    # 修复：取两个概率中的最大值作为置信度
                    if isinstance(prob, dict):
                        prob_positive = prob.get(1, 0.5)
                        prob_negative = prob.get(0, 0.5)
                        confidences.append(max(prob_positive, prob_negative))
                    else:
                        confidences.append(0.5)
                    
                except Exception as e:
                    logger.debug(f"River预测失败 {symbol}: {e}")
            
            if not predictions:
                return None
            
            # 集成预测
            final_prediction = int(np.mean(predictions) > 0.5)
            final_confidence = np.mean(confidences)

            # 添加市场趋势判断来平衡买卖信号
            close_price = df['close'].iloc[-1]
            sma_20 = df['close'].rolling(20).mean().iloc[-1]
            sma_50 = df['close'].rolling(50).mean().iloc[-1] if len(df) > 50 else sma_20
            # 从特征中获取RSI值
            rsi = features['rsi'].iloc[-1] if 'rsi' in features.columns else 50.0

            # 市场趋势调整
            trend_bias = 0
            if close_price > sma_20 and sma_20 > sma_50:
                trend_bias = 0.15  # 上升趋势，增加买入倾向
            elif close_price < sma_20 and sma_20 < sma_50:
                trend_bias = -0.15  # 下降趋势，增加卖出倾向

            # RSI超卖超买调整
            if rsi < 30:
                trend_bias += 0.2  # 超卖，增加买入倾向
            elif rsi > 70:
                trend_bias -= 0.2  # 超买，增加卖出倾向

            # 调整后的预测概率
            adjusted_buy_prob = np.mean(predictions) + trend_bias

            # 应用死区逻辑
            if abs(final_confidence - 0.5) < self.dead_zone:
                recommendation = 'HOLD'
                reason = f'置信度在死区范围内 ({final_confidence:.2%})'
            elif final_confidence < self.min_confidence:
                recommendation = 'HOLD'
                reason = f'置信度不足 ({final_confidence:.2%} < {self.min_confidence:.2%})'
            else:
                # 使用调整后的概率决定买卖
                if adjusted_buy_prob > 0.5:
                    recommendation = 'BUY'
                    reason = f'模型+趋势预测买入 (调整概率: {adjusted_buy_prob:.2f})'
                elif adjusted_buy_prob < 0.5:
                    recommendation = 'SELL'
                    reason = f'模型+趋势预测卖出 (调整概率: {adjusted_buy_prob:.2f})'
                else:
                    recommendation = 'HOLD'
                    reason = '概率中性，持有观望'
            
            # 在线学习：使用历史数据更新River模型
            if len(df) > 50:
                self._update_river_with_history(symbol, df, features)
            
            signal = {
                'symbol': symbol,
                'type': recommendation.lower(),
                'recommendation': recommendation,
                'confidence': final_confidence,
                'reason': reason,
                'models_used': len(predictions),
                'timestamp': datetime.now().isoformat(),
                'source': 'autogluon_river'
            }
            
            # 记录性能指标
            elapsed_time = time.time() - start_time
            logger.debug(f"{symbol} 信号生成耗时: {elapsed_time:.3f}秒")

            return signal

        except Exception as e:
            logger.error(f"生成 {symbol} 信号失败: {e}")
            return None
    
    def _update_river_with_history(self, symbol: str, df: pd.DataFrame, features: pd.DataFrame):
        """使用历史数据更新River模型"""
        try:
            # 只使用最近的数据避免过度训练
            recent_data = df.tail(100)
            recent_features = features.tail(100)
            
            if len(recent_data) < 25:
                return
            
            # 创建标签
            labels = self._create_labels(recent_data, lookforward=1)  # 更短的预测期
            
            # 更新模型
            for i in range(len(recent_features) - 1):  # 排除最后一个（没有标签）
                if not np.isnan(labels.iloc[i]):
                    feature_dict = recent_features.iloc[i].to_dict()
                    # 清理特征
                    feature_dict = {k: v for k, v in feature_dict.items() 
                                  if not (np.isnan(v) or np.isinf(v))}
                    
                    if feature_dict:  # 确保有有效特征
                        self.update_river_model(symbol, feature_dict, int(labels.iloc[i]))
        
        except Exception as e:
            logger.debug(f"River历史更新失败 {symbol}: {e}")
    
    def retrain_all_models(self):
        """重训练所有AutoGluon模型"""
        logger.info("开始重训练所有AutoGluon模型...")
        
        success_count = 0
        for symbol in self.symbols:
            logger.info(f"[{success_count+1}/{len(self.symbols)}] 训练 {symbol}...")
            if self.train_autogluon_model(symbol):
                success_count += 1
            time.sleep(1)  # 避免过载
        
        # 更新重训练时间
        self._last_retrain_date = datetime.now()
        
        logger.info(f"重训练完成: {success_count}/{len(self.symbols)} 个模型成功")
        
        # 保存所有River模型
        for symbol in self.symbols:
            self._save_river_model(symbol)
    
    def check_and_auto_retrain(self):
        """检查并执行自动重训练（每天UTC 12:00）"""
        if not self.enable_auto_retrain:
            return
        
        now = datetime.utcnow()
        # 检查是否是UTC 12:00 (允许30分钟误差)
        if (now.hour == 11 and now.minute >= 30) or (now.hour == 12 and now.minute <= 30):
            if (self._last_retrain_date is None or 
                self._last_retrain_date.date() < now.date()):
                
                logger.info(f"触发自动重训练 (UTC: {now})")
                threading.Thread(target=self.retrain_all_models, daemon=True).start()
    
    def get_all_signals(self) -> Dict:
        """获取所有币种的信号"""
        signals = {}
        
        for symbol in self.symbols:
            signal = self.generate_signal(symbol)
            if signal:
                signals[symbol] = signal
        
        return signals
    
    def run_websocket_server(self, port: int = 8765):
        """运行WebSocket服务器"""
        async def handle_client(websocket):
            try:
                logger.info(f"新客户端连接: {websocket.remote_address}")
                
                # 发送欢迎消息
                welcome_message = {
                    "type": "welcome",
                    "data": {"message": "Connected to AutoGluon+River strategy"}
                }
                await websocket.send(json.dumps(welcome_message))
                
                # 发送初始信号
                signals = self.get_all_signals()
                signal_message = {
                    "type": "signals",
                    "data": signals
                }
                await websocket.send(json.dumps(signal_message))
                logger.info(f"发送了 {len(signals)} 个初始信号")
                
                # 保持连接并定期发送更新
                last_signals = None
                update_count = 0
                while True:
                    await asyncio.sleep(60)  # 每分钟更新
                    signals = self.get_all_signals()

                    # 只有信号发生变化才发送更新
                    if signals and signals != last_signals:
                        update_message = {
                            "type": "signals_update",
                            "data": signals
                        }
                        await websocket.send(json.dumps(update_message))
                        logger.info(f"发送了 {len(signals)} 个更新信号")
                        last_signals = signals

                    # 定期清理内存（每100次更新）
                    update_count += 1
                    if update_count % 100 == 0:
                        import gc
                        gc.collect()
                        logger.debug(f"执行内存清理，已更新 {update_count} 次")
                    
            except websockets.exceptions.ConnectionClosed:
                logger.info("客户端断开连接")
            except Exception as e:
                logger.error(f"WebSocket错误: {e}")
        
        async def main():
            server = await websockets.serve(handle_client, "localhost", port)
            logger.info(f"WebSocket服务器启动在端口 {port}")
            
            # 定期检查重训练
            async def check_retrain():
                while True:
                    await asyncio.sleep(60)  # 每分钟检查
                    self.check_and_auto_retrain()
            
            await asyncio.gather(
                server.wait_closed(),
                check_retrain()
            )
        
        asyncio.run(main())


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='AutoGluon + River 策略')
    parser.add_argument('--train', action='store_true', help='训练所有模型')
    parser.add_argument('--websocket', action='store_true', help='启动WebSocket服务')
    parser.add_argument('--test', action='store_true', help='测试信号生成')
    args = parser.parse_args()
    
    # 初始化策略
    strategy = AutoGluonRiverStrategy(use_hourly_data=True)
    
    if args.train:
        logger.info("开始训练所有模型...")
        strategy.retrain_all_models()
    
    if args.websocket:
        logger.info("启动WebSocket服务...")
        strategy.run_websocket_server()
    
    if args.test:
        logger.info("测试信号生成...")
        signals = strategy.get_all_signals()
        for symbol, signal in signals.items():
            logger.info(f"{symbol}: {signal}")


if __name__ == "__main__":
    main()