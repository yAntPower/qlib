"""
AutoGluon + River 加密货币交易策略 (生产级修复版)

修复的关键问题:
1. 标签泄漏 - 去掉尾部lookforward行
2. 统一lookforward参数
3. 修正概率融合逻辑
4. 过滤未收盘Bar
5. River幂等性和并发安全
6. 特征warmup处理
7. 置信度计算修正
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
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any
from loguru import logger
import time
import argparse
from backtest_repository import BacktestRepository

warnings.filterwarnings('ignore')

# 添加项目路径
sys.path.append('/home/ant/project/qlib/scripts/data_collector/crypto')

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
    AutoGluon + River 集成策略 (生产级)
    """

    def __init__(self, use_hourly_data: bool = True):
        self.use_hourly_data = use_hourly_data
        self.symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'SUIUSDT', 'ADAUSDT', 'DOGEUSDT']

        # 市场情绪数据
        self.fear_greed_value = 50  # 默认中性
        self._last_sentiment_update = 0

        # 初始化网络会话
        self.session = self._create_session()

        # 目录设置
        self.base_dir = os.path.expanduser("~/.qlib")
        self.data_dir = os.path.join(self.base_dir, "binance_hourly_data" if use_hourly_data else "binance_data")
        self.model_dir = os.path.join(self.base_dir, "autogluon_river_models")
        self.river_dir = os.path.join(self.base_dir, "river_models")

        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.model_dir, exist_ok=True)
        os.makedirs(self.river_dir, exist_ok=True)

        # 模型容器
        self.autogluon_models = {}
        self.river_models = {}
        self.feature_columns = {}

        # 重要参数
        self.min_confidence = float(os.environ.get('ML_MIN_CONFIDENCE', '0.55'))
        self.dead_zone = float(os.environ.get('ML_DEAD_ZONE', '0.05'))
        self.lookforward = int(os.environ.get('ML_LOOKFORWARD', '6'))  # 减少到6小时，更实际
        self.warmup = 50
        self.river_save_interval = int(os.environ.get('RIVER_SAVE_INTERVAL', '20'))  # River模型保存间隔

        # 特征列元数据路径
        self._feature_meta_path = os.path.join(self.model_dir, "_feature_columns.json")

        # 并发控制
        self._training_lock = threading.RLock()
        self._river_lock = threading.RLock()
        self._last_retrain_date = None
        self._feature_version = {}  # 特征版本跟踪
        self._feature_stats = {}  # 特征统计信息（用于填充）
        self.enable_auto_retrain = True
        self._is_training = False
        self._auto_retrain_triggered_date = None
        self._auto_retrain_window_minutes = 60  # UTC 12:00 ±30 分钟
        self._retrain_check_interval = 60       # 每60秒检测一次
        self._last_retrain_check_ts = 0.0

        # 扩展配置
        self.label_method = os.environ.get('ML_LABEL_METHOD', 'dynamic')  # dynamic | balanced | percentile
        self.use_quantile_decision = os.environ.get('USE_QUANTILE_DECISION', 'true').lower() == 'true'
        self.min_samples_for_quantile = 300
        self.calibration_target_mean = 0.5
        # 收紧目标标准差以避免概率被过度拉伸
        self.calibration_target_std = 0.08
        # 限制校准缩放，防止小sigma导致概率塌陷
        self.calibration_scale_min = 0.5
        self.calibration_scale_max = 2.0

        # 概率历史记录（用于分位数决策）
        import collections
        self._prob_history = {s: collections.deque(maxlen=2000) for s in self.symbols}

        backtest_dir = os.getenv('QLIB_BACKTEST_DIR')
        if not backtest_dir:
            file_dir = os.getenv('QLIB_FILE_DIR')
            if file_dir:
                backtest_dir = os.path.join(file_dir, 'backtests')
            else:
                backtest_dir = os.path.expanduser('~/.qlib/backtests')
        refresh_interval = int(os.getenv('QLIB_BACKTEST_REFRESH_INTERVAL', os.getenv('BACKTEST_REFRESH_INTERVAL', '300')))
        self.backtest_repo = BacktestRepository(backtest_dir, refresh_interval=refresh_interval)

        logger.info(f"策略初始化: lookforward={self.lookforward}, warmup={self.warmup}")

        # 加载特征列配置和元数据
        self._load_feature_columns()
        self._load_feature_metadata()

        # 初始化模型
        self._initialize_models()

        # 获取市场情绪
        self._update_market_sentiment()

    def _create_session(self) -> requests.Session:
        """创建带重试机制的网络会话"""
        session = requests.Session()
        retry = Retry(
            total=3,
            read=3,
            connect=3,
            backoff_factor=0.3,
            status_forcelist=(500, 502, 504)
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session

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

    def _save_feature_metadata(self):
        """持久化特征版本和统计信息"""
        try:
            metadata = {
                'versions': {k: v for k, v in self._feature_version.items()},
                'stats': self._feature_stats,
                'last_update': datetime.utcnow().isoformat()
            }
            metadata_path = os.path.join(self.model_dir, "_feature_metadata.json")
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            logger.debug("特征元数据已保存")
        except Exception as e:
            logger.warning(f"特征元数据保存失败: {e}")

    def _load_feature_metadata(self):
        """加载特征元数据"""
        metadata_path = os.path.join(self.model_dir, "_feature_metadata.json")
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                    self._feature_version = {k: int(v) for k, v in metadata.get('versions', {}).items()}
                    self._feature_stats = metadata.get('stats', {})
                    logger.info(f"已加载特征元数据，版本: {list(self._feature_version.keys())}")
            except Exception as e:
                logger.warning(f"加载特征元数据失败: {e}")

    def _initialize_models(self):
        """初始化所有模型"""
        for symbol in self.symbols:
            self._load_autogluon_model(symbol)
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

    def _initialize_river_model(self, symbol: str):
        """初始化River在线学习模型"""
        river_path = os.path.join(self.river_dir, f"{symbol}_river.pkl")
        if os.path.exists(river_path):
            try:
                with open(river_path, 'rb') as f:
                    obj = pickle.load(f)
                # 向后兼容：补充缺失字段
                if isinstance(obj, dict):
                    obj.setdefault('updates_since_save', 0)
                    obj.setdefault('last_train_ts', None)
                    obj.setdefault('feature_version', None)

                    # 检查特征版本兼容性
                    if symbol in self._feature_version:
                        current_version = self._feature_version[symbol]
                        saved_version = obj.get('feature_version')
                        if saved_version and saved_version != current_version:
                            logger.warning(f"{symbol} River模型特征版本不匹配 (saved:{saved_version} != current:{current_version})，重新创建")
                            self._create_new_river_model(symbol)
                            return

                    self.river_models[symbol] = obj
                else:
                    # 旧格式，需要重建
                    self._create_new_river_model(symbol)
                logger.info(f"已加载 {symbol} River模型")
            except Exception as e:
                logger.warning(f"加载 {symbol} River模型失败: {e}")
                self._create_new_river_model(symbol)
        else:
            self._create_new_river_model(symbol)

    def _create_new_river_model(self, symbol: str):
        """创建新的River在线模型"""
        from river import tree
        model = compose.Pipeline(
            preprocessing.StandardScaler(),
            ensemble.BaggingClassifier(
                model=tree.HoeffdingTreeClassifier(),
                n_models=8,
                seed=42
            )
        )

        self.river_models[symbol] = {
            'model': model,
            'accuracy': metrics.Accuracy(),
            'samples_processed': 0,
            'last_updated': datetime.utcnow(),
            'last_train_ts': None,
            'updates_since_save': 0,  # 跟踪未保存的更新次数
            'feature_version': self._feature_version.get(symbol),  # 特征版本
            'feature_stats': self._feature_stats.get(symbol) if symbol in self._feature_stats else None  # 特征统计
        }
        logger.info(f"创建新的 {symbol} River模型")

    def _calibrate_prob(self, symbol: str, p: float) -> float:
        """线性概率校准 - 基于文档中的公式"""
        stats = self._feature_stats.get(symbol, {})
        mu = stats.get('prob_mean')
        sigma = stats.get('prob_std')

        if mu is None or sigma is None:
            # 无统计信息时返回原值
            return p

        if sigma < 5e-4:
            # 分布塌缩时直接回归目标均值，避免放大量化噪声
            return self.calibration_target_mean

        # 使用文档中的校准公式: p_cal = clip((p - μ)σ_t/σ + μ_t, 0, 1)
        mu_t = self.calibration_target_mean
        sigma_t = self.calibration_target_std

        scale = sigma_t / max(sigma, 1e-6)
        # 限制缩放倍数，避免将中性概率压得过低或拉得过高
        scale = float(np.clip(scale, self.calibration_scale_min, self.calibration_scale_max))

        p_cal = (p - mu) * scale + mu_t

        return float(np.clip(p_cal, 0, 1))

    def _decision_from_quantiles(self, symbol: str, p: float) -> tuple:
        """基于历史分位数的决策（替代固定0.5）"""
        hist = self._prob_history[symbol]

        if len(hist) < self.min_samples_for_quantile or not self.use_quantile_decision:
            # 回退逻辑：使用中位数而非固定0.5
            arr = np.array(hist)
            median = 0.5 if len(arr) == 0 else float(np.median(arr))

            # 计算IQR用于置信度
            if len(arr) >= 20:
                q25, q75 = np.percentile(arr, [25, 75])
                iqr = max(q75 - q25, 1e-6)
            else:
                iqr = 0.25

            # 基于与中位数的距离计算置信度
            confidence = float(np.clip(abs(p - median) / (iqr / 2), 0, 1))

            if confidence < self.dead_zone:
                return 'HOLD', confidence, {'mode': 'fallback_median', 'reason': 'dead_zone', 'median': median}

            rec = 'BUY' if p > median else 'SELL'

            if confidence < self.min_confidence:
                return 'HOLD', confidence, {'mode': 'fallback_median', 'reason': 'min_conf', 'median': median}

            return rec, confidence, {'mode': 'fallback_median', 'median': median}

        # 使用分位数决策
        arr = np.array(hist)
        q20, q50, q80 = np.quantile(arr, [0.2, 0.5, 0.8])
        span = q80 - q20

        # Span退化检测：分布过窄时回退到中位数逻辑
        if span < 0.01:
            # 视为信息不足：回退到中位数逻辑
            median = q50
            iqr = max(q80 - q20, 1e-6)
            confidence = float(np.clip(abs(p - median) / (iqr / 2), 0, 1))

            if confidence < self.dead_zone:
                return 'HOLD', confidence, {'mode': 'quantile_fallback', 'reason': 'span_collapse', 'median': median, 'span': span}

            rec = 'BUY' if p > median else 'SELL'

            if confidence < self.min_confidence:
                return 'HOLD', confidence, {'mode': 'quantile_fallback', 'reason': 'min_conf', 'median': median, 'span': span}

            return rec, confidence, {'mode': 'quantile_fallback', 'median': median, 'span': span}

        # 正常span情况
        span = max(span, 1e-6)  # 防止除零

        if p > q80:
            rec = 'BUY'
            # 距离q80往上推进的幅度，相对span缩放到[0.5,1]
            confidence = 0.5 + 0.5 * min((p - q80) / span, 1.0)
        elif p < q20:
            rec = 'SELL'
            # 距离q20往下推进的幅度，相对span缩放到[0.5,1]
            confidence = 0.5 + 0.5 * min((q20 - p) / span, 1.0)
        else:
            rec = 'HOLD'
            # HOLD区间内，使用到中位数的距离，相对半span归一化
            confidence = abs(p - q50) / (span / 2)
            # 可选：限制HOLD置信度上限，避免过度自信
            confidence = min(confidence, 0.6)

        confidence = float(np.clip(confidence, 0, 1))

        # 统一过滤：对BUY/SELL应用min_confidence和dead_zone
        if rec != 'HOLD':
            if confidence < self.dead_zone:
                return 'HOLD', confidence, {'mode': 'quantile', 'reason': 'dead_zone', 'q20': float(q20), 'q80': float(q80), 'p': float(p)}
            if confidence < self.min_confidence:
                return 'HOLD', confidence, {'mode': 'quantile', 'reason': 'min_conf', 'q20': float(q20), 'q80': float(q80), 'p': float(p)}

        return rec, confidence, {
            'mode': 'quantile',
            'q20': float(q20),
            'q50': float(q50),
            'q80': float(q80),
            'p': float(p),
            'span': float(span)
        }

    def _save_river_model(self, symbol: str):
        """持久化River模型"""
        try:
            river_path = os.path.join(self.river_dir, f"{symbol}_river.pkl")
            with open(river_path, 'wb') as f:
                pickle.dump(self.river_models[symbol], f)
            logger.debug(f"{symbol} River模型已保存")
        except Exception as e:
            logger.warning(f"{symbol} River模型保存失败: {e}")

    def _load_data(self, symbol: str) -> pd.DataFrame:
        """加载数据"""
        try:
            file_path = os.path.join(self.data_dir, f"{symbol}.csv")
            if not os.path.exists(file_path):
                self._download_historical_data(symbol)

            df = pd.read_csv(file_path)
            df['date'] = pd.to_datetime(df['date'], utc=True)  # 显式指定UTC
            df = df.sort_values('date').reset_index(drop=True)

            # 增量更新
            self._update_latest_data(symbol, df, file_path)

            # 重新加载
            df = pd.read_csv(file_path)
            df['date'] = pd.to_datetime(df['date'], utc=True)  # 显式指定UTC

            return df.sort_values('date').reset_index(drop=True)

        except Exception as e:
            logger.error(f"加载 {symbol} 数据失败: {e}")
            return pd.DataFrame()

    def _update_latest_data(self, symbol: str, df: pd.DataFrame, file_path: str):
        """增量更新（循环补齐，避免断档）"""
        try:
            if df.empty:
                return

            last_dt = df['date'].max()
            if pd.isna(last_dt):
                return

            # 转换为datetime对象，确保timezone一致
            if isinstance(last_dt, pd.Timestamp):
                last_dt = last_dt.to_pydatetime()

            # 确保last_dt是tz-naive（去掉时区信息）
            if last_dt.tzinfo is not None:
                last_dt = last_dt.replace(tzinfo=None)

            now_utc = datetime.utcnow()  # 这是tz-naive
            # 现在两个都是tz-naive，可以安全比较
            gap_hours = (now_utc - last_dt).total_seconds() / 3600

            if gap_hours < 2:
                return

            interval = '1h' if self.use_hourly_data else '1d'
            url = "https://api.binance.com/api/v3/klines"
            new_rows = []

            # 根据数据类型设置正确的步进
            step = timedelta(hours=1) if self.use_hourly_data else timedelta(days=1)
            start_time = last_dt + step

            while start_time < now_utc and len(new_rows) < 5000:  # 限制最多5000条
                # 计算正确的limit
                if self.use_hourly_data:
                    limit_est = int((now_utc - start_time).total_seconds() / 3600) + 1
                else:
                    limit_est = int((now_utc - start_time).total_seconds() / 86400) + 1

                # 避免请求未来数据
                if limit_est <= 0:
                    break

                params = {
                    'symbol': symbol,
                    'interval': interval,
                    'startTime': int(start_time.timestamp() * 1000),
                    'limit': min(1000, max(1, limit_est))
                }

                resp = requests.get(url, params=params, timeout=20)
                if resp.status_code != 200:
                    break

                batch = resp.json()
                if not batch:
                    break

                new_rows.extend(batch)

                # 更新起始时间（使用正确的步进）
                last_timestamp = batch[-1][0]
                next_start = datetime.utcfromtimestamp(last_timestamp / 1000) + step

                # 避免无限循环：如果时间没有推进，强制退出
                if next_start <= start_time:
                    break

                start_time = next_start

                # 如果已经到达当前时间，退出
                if start_time >= now_utc:
                    break

                if len(batch) < params['limit']:
                    break

                time.sleep(0.1)  # 避免频率限制

            if new_rows:
                new_df = pd.DataFrame(new_rows, columns=[
                    'timestamp', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                    'taker_buy_quote', 'ignore'
                ])

                new_df['date'] = pd.to_datetime(new_df['timestamp'], unit='ms', utc=True)
                new_df = new_df[['date', 'open', 'high', 'low', 'close', 'volume']]

                for col in ['open', 'high', 'low', 'close', 'volume']:
                    new_df[col] = pd.to_numeric(new_df[col], errors='coerce')

                # 合并并去重
                merged = pd.concat([df, new_df]).drop_duplicates('date').sort_values('date')
                merged.to_csv(file_path, index=False)

                logger.debug(f"{symbol} 增量补齐 {len(new_df)} 行")

        except Exception as e:
            logger.warning(f"{symbol} 增量更新失败: {e}")

    def _create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """创建特征（改进版，避免填0）"""
        f = pd.DataFrame(index=df.index)

        close = df['close']
        vol = df['volume']

        # 价格特征
        f['ret_1'] = close.pct_change()
        f['log_ret_1'] = np.log(close / close.shift(1))
        f['high_low_pct'] = (df['high'] - df['low']) / close
        f['close_open_pct'] = (close - df['open']) / df['open']

        # 移动平均
        for w in [5, 10, 20, 50]:
            ma = close.rolling(w).mean()
            f[f'sma_{w}'] = ma
            f[f'price_sma_{w}_pct'] = close / ma - 1

        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        sig = macd.ewm(span=9, adjust=False).mean()
        f['macd'] = macd
        f['macd_signal'] = sig
        f['macd_hist'] = macd - sig

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / (loss + 1e-10)
        f['rsi'] = 100 - (100 / (1 + rs))

        # 布林带
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        f['bb_width'] = (std20 * 4) / sma20
        f['bb_position'] = (close - (sma20 - std20*2)) / (std20*4 + 1e-10)

        # 成交量
        f['volume_z'] = (vol - vol.rolling(30).mean()) / (vol.rolling(30).std() + 1e-10)
        f['volume_ratio'] = vol / vol.rolling(20).mean()

        # 波动率
        f['vol_20'] = close.pct_change().rolling(20).std()
        f['vol_50'] = close.pct_change().rolling(50).std()

        # 更多技术指标
        # ATR (Average True Range)
        high = df['high']
        low = df['low']
        tr = pd.DataFrame({
            'hl': high - low,
            'hc': (high - close.shift()).abs(),
            'lc': (low - close.shift()).abs()
        }).max(axis=1)
        f['atr_14'] = tr.rolling(14).mean()
        f['atr_ratio'] = f['atr_14'] / close

        # 价格位置（相对于近期高低点）
        highest_20 = high.rolling(20).max()
        lowest_20 = low.rolling(20).min()
        f['price_position'] = (close - lowest_20) / (highest_20 - lowest_20 + 1e-10)

        # 成交量加权价格
        vwap = (close * vol).rolling(20).sum() / (vol.rolling(20).sum() + 1e-10)
        f['vwap_ratio'] = close / vwap - 1

        # 市场情绪特征
        f['fear_greed'] = self.fear_greed_value / 100.0  # 归一化到0-1
        f['sentiment_extreme'] = abs(self.fear_greed_value - 50) / 50.0  # 极端程度

        # 丢弃前warmup期并去除缺失（不填0）
        f = f.iloc[self.warmup:].replace([np.inf, -np.inf], np.nan).dropna()

        return f

    def _create_labels(self, df: pd.DataFrame) -> pd.Series:
        """创建标签（正确版本，无数据泄漏）"""
        close = df['close']
        # 正确：计算未来收益率作为标签（这是我们要预测的）
        future = close.shift(-self.lookforward)
        ret_fwd = future / close - 1

        if self.label_method == 'balanced':
            # 平衡标签：使用中位数分割，保证50/50
            threshold = ret_fwd.median()
            label = (ret_fwd > threshold).astype(int)
            logger.debug(f"使用平衡标签，阈值={threshold:.4f}")
        elif self.label_method == 'percentile':
            # 分位数标签：上40%为1
            up_q = ret_fwd.quantile(0.6)
            label = (ret_fwd > up_q).astype(int)
            logger.debug(f"使用分位数标签，60分位={up_q:.4f}")
        else:
            # 默认：动态阈值（可能导致不平衡）
            vol = close.pct_change().rolling(48).std()
            dyn = (0.25 * vol).clip(lower=0.002)
            label = (ret_fwd > dyn).astype(int)

        # 重要：去掉尾部lookforward行（这些行没有未来数据来创建标签）
        label = label.iloc[:-self.lookforward]

        # 修复早期偏置：删除NaN值
        label = label.dropna()

        return label

    def train_autogluon_model(self, symbol: str) -> bool:
        """训练AutoGluon模型"""
        if not AUTOGLUON_AVAILABLE:
            return False

        try:
            logger.info(f"开始训练 {symbol} AutoGluon模型...")

            df = self._load_data(symbol)
            if len(df) < 600:
                logger.warning(f"{symbol} 数据不足")
                return False

            df = df.sort_values('date').reset_index(drop=True)
            feats = self._create_features(df)
            df_align = df.loc[feats.index]
            labels = self._create_labels(df_align)

            # 对齐
            feats = feats.loc[labels.index]

            if len(feats) < 400:
                logger.warning(f"{symbol} 有效样本不足")
                return False

            # 记录标签分布
            pos_ratio = labels.mean()
            logger.info(f"{symbol} 标签分布: 正类比例={pos_ratio:.3f}, 样本数={len(labels)}")

            # 保存特征列
            self.feature_columns[symbol] = list(feats.columns)
            self._save_feature_columns()

            # 时序分割（避免数据泄漏）
            # 使用70%训练，10%验证，20%测试
            train_split = int(len(feats) * 0.7)
            val_split = int(len(feats) * 0.8)

            train_df = pd.concat([feats.iloc[:train_split], labels.iloc[:train_split].rename('label')], axis=1)
            val_df = pd.concat([feats.iloc[train_split:val_split], labels.iloc[train_split:val_split].rename('label')], axis=1)
            test_df = pd.concat([feats.iloc[val_split:], labels.iloc[val_split:].rename('label')], axis=1)

            logger.info(f"{symbol} 训练集: {len(train_df)}, 测试集: {len(test_df)}")

            # AutoGluon训练
            model_path = os.path.join(self.model_dir, f"{symbol}_autogluon")

            import shutil
            if os.path.exists(model_path):
                shutil.rmtree(model_path)

            # 固定为二分类（标签生成始终是二分类）
            predictor = TabularPredictor(
                label='label',
                problem_type='binary',
                eval_metric='roc_auc',  # 使用ROC-AUC作为评估指标
                path=model_path
                # 注意：如需设置随机种子，可在fit的ag_args参数中设置
            )

            predictor.fit(
                train_data=train_df,
                time_limit=180,
                presets='medium_quality_faster_train',
                verbosity=1
                # AutoGluon使用TabularPredictor的seed参数，不是在fit中设置
            )

            self.autogluon_models[symbol] = predictor

            # 评估（修复dict取值）
            perf = predictor.evaluate(test_df, silent=True)
            auc = perf.get('roc_auc', 0.5)
            acc = perf.get('accuracy', 0.5)
            logger.info(f"{symbol} 测试性能: AUC={auc:.4f}, ACC={acc:.4f}, 测试集大小={len(test_df)}")

            # 统计测试集预测概率用于后续校准
            try:
                proba_df = predictor.predict_proba(test_df.drop(columns=['label']))
                if hasattr(proba_df, 'columns') and 1 in proba_df.columns:
                    probs = proba_df[1].values
                else:
                    probs = proba_df.iloc[:, -1].values

                self._feature_stats.setdefault(symbol, {})
                self._feature_stats[symbol]['prob_mean'] = float(np.mean(probs))
                self._feature_stats[symbol]['prob_std'] = float(np.std(probs) + 1e-8)
                self._save_feature_metadata()
                logger.info(f"{symbol} 概率分布: mean={self._feature_stats[symbol]['prob_mean']:.4f}, std={self._feature_stats[symbol]['prob_std']:.4f}")
            except Exception as e:
                logger.warning(f"{symbol} 概率统计失败: {e}")

            return True

        except Exception as e:
            logger.error(f"训练 {symbol} 失败: {e}")
            return False

    def _update_river_incremental(self, symbol: str, df: pd.DataFrame, feats: pd.DataFrame):
        """River增量更新（幂等 + 定期持久化）"""
        if symbol not in self.river_models:
            return

        with self._river_lock:
            info = self.river_models[symbol]
            last_ts = info.get('last_train_ts')

            # 取最近80行
            recent_idx = feats.index[-80:]
            df_recent = df.loc[recent_idx]
            feats_recent = feats.loc[recent_idx]
            labels = self._create_labels(df_recent)
            feats_recent = feats_recent.loc[labels.index]
            df_recent = df_recent.loc[labels.index]

            for i, idx in enumerate(feats_recent.index):
                ts = df_recent.loc[idx, 'date']

                # 幂等性检查
                if last_ts and ts <= last_ts:
                    continue

                feat_row = feats_recent.iloc[i]
                if feat_row.isna().any():
                    continue

                y = int(labels.iloc[i])

                # 预测并更新
                y_pred = info['model'].predict_one(feat_row.to_dict())
                info['accuracy'].update(y, y_pred)
                info['model'].learn_one(feat_row.to_dict(), y)
                info['samples_processed'] += 1
                info['last_train_ts'] = ts
                info['updates_since_save'] += 1

                # 定期保存模型
                if info['updates_since_save'] >= self.river_save_interval:
                    self._save_river_model(symbol)
                    info['updates_since_save'] = 0

    def _apply_backtest_feedback(self, symbol: str, signal: Dict) -> Dict:
        repository = getattr(self, 'backtest_repo', None)
        if not repository:
            return signal

        record = repository.get_latest(symbol)
        if not record:
            return signal

        backtest_meta = repository.as_dict(record)
        signal.setdefault('metadata', {})
        signal['metadata']['backtest'] = backtest_meta
        signal.setdefault('risk_metrics', {})
        signal['risk_metrics']['backtest_quality'] = backtest_meta['quality']

        quality = backtest_meta['quality']
        adjustment = 'referenced'

        if quality == 'weak':
            prev = signal.get('recommendation')
            signal['confidence'] = min(signal.get('confidence', 0.0), 0.45)
            if prev and prev.upper() != 'HOLD':
                signal['metadata']['backtest']['original_recommendation'] = prev
                signal['recommendation'] = 'HOLD'
                signal['type'] = 'hold'
                adjustment = f'downgraded_from_{prev}'
            else:
                adjustment = 'confidence_capped'
        elif quality == 'strong':
            signal['confidence'] = min(0.99, signal.get('confidence', 0.0) * 1.08)
            adjustment = 'boosted_confidence'

        signal['metadata']['backtest']['action'] = adjustment
        signal['metadata']['backtest']['timestamp'] = backtest_meta['generated_at']
        logger.debug(f"Backtest feedback applied to {symbol}: quality={quality}, action={adjustment}")
        return signal

    def generate_signal(self, symbol: str) -> Optional[Dict]:
        """生成交易信号（修正版）"""
        start_time = time.time()

        # 添加读锁保护（避免训练期间读取不完整模型）
        with self._training_lock:
            try:
                df = self._load_data(symbol)
                if len(df) < 300:
                    return None

                df = df.sort_values('date').reset_index(drop=True)

                # 严格过滤未收盘Bar（生产环境关键）
                last_open = df['date'].iloc[-1]
                now_utc = datetime.utcnow()
                interval_sec = 3600 if self.use_hourly_data else 86400

                if isinstance(last_open, pd.Timestamp):
                    last_open = last_open.to_pydatetime()

                # 使用更严格的时间窗口（至少等待5分钟确保K线完成）
                time_since_open = (now_utc - last_open.replace(tzinfo=None)).total_seconds()
                if time_since_open < interval_sec + 300:  # 增加5分钟缓冲
                    df = df.iloc[:-1]  # 去掉当前未完成的Bar
                    logger.debug(f"{symbol}: 移除未完成K线，时间差={time_since_open}秒")

                feats = self._create_features(df)
                if feats.empty:
                    return None

                df_align = df.loc[feats.index]
                latest_feat = feats.iloc[-1]

                buy_probs = []  # 直接收集买入概率

                # AutoGluon概率
                if (symbol in self.autogluon_models and
                    self.autogluon_models[symbol] is not None and
                    symbol in self.feature_columns):
                    try:
                        feat_df = pd.DataFrame([latest_feat])
                        feat_df = feat_df.reindex(columns=self.feature_columns[symbol], fill_value=0)
                        proba_df = self.autogluon_models[symbol].predict_proba(feat_df)

                        if hasattr(proba_df, 'columns') and 1 in proba_df.columns:
                            buy_probs.append(float(proba_df[1].iloc[0]))
                        else:
                            buy_probs.append(float(proba_df.iloc[0, -1]))

                    except Exception as e:
                        logger.debug(f"{symbol} AutoGluon预测失败: {e}")

                # River概率
                if symbol in self.river_models and self.river_models[symbol]['samples_processed'] > 50:
                    with self._river_lock:
                        try:
                            prob = self.river_models[symbol]['model'].predict_proba_one(latest_feat.to_dict())
                            buy_probs.append(prob.get(1, 0.5))
                        except Exception as e:
                            logger.debug(f"{symbol} River预测失败: {e}")

                if not buy_probs:
                    # 异常兜底：无模型可用时返回HOLD
                    logger.warning(f"{symbol} 无可用模型，返回HOLD")
                    return {
                        'symbol': symbol,
                        'type': 'hold',
                        'recommendation': 'HOLD',
                        'buy_prob': 0.5,
                        'raw_buy_prob': 0.5,
                        'confidence': 0.0,
                        'price': float(df_align['close'].iloc[-1]),
                        'models_used': 0,
                        'timestamp': datetime.utcnow().isoformat(),
                        'reason': '无可用模型',
                        'source': 'autogluon_river_fixed'
                    }

                # 概率融合（正确方式）
                raw_buy_prob = float(np.mean(buy_probs))

                # 轻量趋势偏置（收缩到±0.1）
                close = df_align['close'].iloc[-1]
                sma20 = df_align['close'].rolling(20).mean().iloc[-1]
                sma50 = df_align['close'].rolling(50).mean().iloc[-1] if len(df_align) >= 50 else sma20
                rsi = feats['rsi'].iloc[-1] if 'rsi' in feats.columns else 50

                bias = 0.0
                if close > sma20 > sma50:
                    bias += 0.05
                elif close < sma20 < sma50:
                    bias -= 0.05

                if rsi < 30:
                    bias += 0.05
                elif rsi > 70:
                    bias -= 0.05

                adjusted_buy_prob = float(np.clip(raw_buy_prob + bias, 0, 1))

                # 概率校准
                calibrated_prob = self._calibrate_prob(symbol, adjusted_buy_prob)

                # 更新历史记录
                self._prob_history[symbol].append(calibrated_prob)

                # 在线更新原始分布统计（使用raw_buy_prob避免bias污染）
                stats = self._feature_stats.setdefault(symbol, {})
                raw_mu = stats.get('prob_mean')
                raw_std = stats.get('prob_std')

                # 使用raw_buy_prob（未加bias）更新统计，避免bias污染
                base_prob_for_stats = raw_buy_prob

                # 指数滑动更新
                alpha = 0.02  # 学习率
                if raw_mu is None:
                    # 首次初始化
                    stats['prob_mean'] = float(base_prob_for_stats)
                    stats['prob_std'] = 0.05
                else:
                    # 指数移动平均更新均值
                    prev_mu = stats['prob_mean']
                    new_mu = (1 - alpha) * prev_mu + alpha * base_prob_for_stats

                    # Welford近似（简单指数版本）更新方差
                    new_var = (1 - alpha) * (raw_std ** 2) + alpha * (base_prob_for_stats - new_mu) ** 2

                    stats['prob_mean'] = float(new_mu)
                    stats['prob_std'] = float(np.sqrt(max(new_var, 1e-8)))

                    # 定期持久化更新后的统计信息
                    if np.random.random() < 0.1:  # 10%概率保存，避免频繁IO
                        try:
                            self._save_feature_metadata()
                        except Exception as e:
                            logger.debug(f"保存特征元数据失败: {e}")

                # 使用分位数决策（或回退到传统逻辑）
                rec, confidence, meta = self._decision_from_quantiles(symbol, calibrated_prob)

                # 构建原因说明
                if rec == 'HOLD':
                    if 'reason' in meta:
                        reason = f"HOLD | p_cal={calibrated_prob:.3f} ({meta['reason']})"
                    else:
                        reason = f"HOLD | p_cal={calibrated_prob:.3f} (q20={meta.get('q20', 0):.3f}, q80={meta.get('q80', 1):.3f})"
                else:
                    if meta['mode'] == 'quantile':
                        reason = f"{rec} | raw={raw_buy_prob:.3f} cal={calibrated_prob:.3f} (q20={meta['q20']:.3f}, q80={meta['q80']:.3f})"
                    else:
                        reason = f"{rec} | raw={raw_buy_prob:.3f} cal={calibrated_prob:.3f} ({meta['mode']})"

                # 增量在线更新
                self._update_river_incremental(symbol, df_align, feats)

                # 性能记录
                elapsed = time.time() - start_time
                logger.debug(f"{symbol} 信号生成耗时: {elapsed:.3f}秒")

                signal = {
                    'symbol': symbol,
                    'type': rec.lower(),
                    'recommendation': rec,
                    'buy_prob': round(calibrated_prob, 4),
                    'raw_buy_prob': round(raw_buy_prob, 4),
                    'adjusted_prob': round(adjusted_buy_prob, 4),
                    'confidence': round(confidence, 4),
                    'price': float(close),
                    'models_used': len(buy_probs),
                    'timestamp': datetime.utcnow().isoformat(),
                    'reason': reason,
                    'decision_mode': meta.get('mode', 'unknown'),
                    'quantiles': {
                        'q20': meta.get('q20', 0),
                        'q50': meta.get('q50', 0.5),
                        'q80': meta.get('q80', 1)
                    } if meta.get('mode') == 'quantile' else None,
                    'source': 'autogluon_river_fixed'
                }

                signal = self._apply_backtest_feedback(symbol, signal)
                return signal

            except Exception as e:
                logger.error(f"{symbol} 信号生成失败: {e}")
                return None

    def retrain_all_models(self) -> bool:
        """重训所有模型"""
        with self._training_lock:
            if self._is_training:
                logger.warning("模型正在训练中，跳过本次训练请求")
                return False
            self._is_training = True

        start_utc = datetime.utcnow()
        try:
            logger.info(f"开始重训所有模型 (UTC时间: {start_utc})")
            for idx, symbol in enumerate(self.symbols, 1):
                logger.info(f"训练进度: [{idx}/{len(self.symbols)}] 正在训练 {symbol} 模型...")
                self.train_autogluon_model(symbol)
                logger.info(f"✓ {symbol} 模型训练完成")

            self._last_retrain_date = datetime.utcnow()
            self._auto_retrain_triggered_date = self._last_retrain_date.date()
            logger.info("所有模型重训完成")
            return True
        except Exception as e:
            logger.error(f"模型重训失败: {e}")
            return False
        finally:
            with self._training_lock:
                self._is_training = False

    def check_and_auto_retrain(self):
        """检测是否需要在UTC 12:00附近自动重训"""
        if not self.enable_auto_retrain:
            return

        now_utc = datetime.utcnow()

        # 今日已触发，跳过
        if self._auto_retrain_triggered_date == now_utc.date():
            return

        # 计算窗口：UTC 12:00 ± window/2
        target_utc = now_utc.replace(hour=12, minute=0, second=0, microsecond=0)
        window_half_seconds = (self._auto_retrain_window_minutes / 2) * 60
        if abs((now_utc - target_utc).total_seconds()) > window_half_seconds:
            return

        if self._is_training:
            logger.debug("自动重训练窗口内但模型仍在训练中，跳过本次检查")
            return

        logger.info(f"触发自动重训练 (UTC: {now_utc}, Local: {datetime.now()})")
        self._auto_retrain_triggered_date = now_utc.date()

        def _run():
            success = self.retrain_all_models()
            if not success:
                logger.warning("自动重训练失败，将允许稍后重试")
                self._auto_retrain_triggered_date = None

        threading.Thread(target=_run, daemon=True).start()

    def force_download_all_hourly_data(self):
        """强制重新下载所有币种的历史数据"""
        logger.info("开始强制重新下载所有历史数据...")
        for symbol in self.symbols:
            try:
                logger.info(f"正在下载 {symbol} 的完整历史数据...")
                file_path = os.path.join(self.data_dir, f"{symbol}.csv")

                # 删除旧文件（如果存在）
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"已删除旧的 {symbol} 数据文件")

                # 下载新数据
                self._download_historical_data(symbol)

                # 验证下载结果
                if os.path.exists(file_path):
                    df = pd.read_csv(file_path)
                    logger.info(f"{symbol} 下载完成: {len(df)} 条记录")
                else:
                    logger.error(f"{symbol} 下载失败")

            except Exception as e:
                logger.error(f"下载 {symbol} 失败: {e}")

        logger.info("所有历史数据下载完成")

    def get_all_signals(self) -> Dict[str, Dict]:
        """获取所有信号"""
        signals = {}
        for symbol in self.symbols:
            signal = self.generate_signal(symbol)
            if signal:
                signals[symbol] = signal
        return signals

    def _download_historical_data(self, symbol: str):
        """下载历史数据"""
        try:
            logger.info(f"开始下载 {symbol} 历史数据...")
            url = "https://api.binance.com/api/v3/klines"

            all_data = []
            interval = '1h' if self.use_hourly_data else '1d'
            limit = 1000

            end_time = int(datetime.utcnow().timestamp() * 1000)

            # 根据币种设置不同的开始时间
            if symbol == 'SUIUSDT':
                # SUI: 2023年5月上线
                start_time = int(datetime(2023, 5, 3).timestamp() * 1000)
            elif symbol in ['SOLUSDT']:
                # SOL: 2020年8月在币安上线
                start_time = int(datetime(2020, 8, 11).timestamp() * 1000)
            elif symbol in ['DOGEUSDT']:
                # DOGE: 2019年7月在币安上线
                start_time = int(datetime(2019, 7, 5).timestamp() * 1000)
            else:
                # 其他币种: 获取5年数据
                start_time = end_time - (365 * 5 * 24 * 60 * 60 * 1000)

            while start_time < end_time:
                params = {
                    'symbol': symbol,
                    'interval': interval,
                    'startTime': start_time,
                    'limit': limit
                }

                response = requests.get(url, params=params, timeout=30)
                if response.status_code != 200:
                    break

                data = response.json()
                if not data:
                    break

                all_data.extend(data)
                # 修复：加上完整的interval以避免重复
                interval_ms = 3600000 if self.use_hourly_data else 86400000  # 1h or 1d in ms
                start_time = data[-1][0] + interval_ms
                time.sleep(0.1)

            if all_data:
                df = pd.DataFrame(all_data, columns=[
                    'timestamp', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                    'taker_buy_quote', 'ignore'
                ])

                df['date'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
                df = df[['date', 'open', 'high', 'low', 'close', 'volume']]

                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

                file_path = os.path.join(self.data_dir, f"{symbol}.csv")
                df.to_csv(file_path, index=False)

                logger.info(f"{symbol} 下载完成: {len(df)} 条记录")
                return True

        except Exception as e:
            logger.error(f"下载 {symbol} 数据失败: {e}")

        return False

    def _update_market_sentiment(self):
        """获取市场恐贪指数"""
        try:
            current_time = time.time()
            # 30分钟更新一次
            if current_time - self._last_sentiment_update < 1800:
                return

            response = self.session.get(
                "https://api.alternative.me/fng/",
                timeout=5
            )

            if response.status_code == 200:
                data = response.json()
                if 'data' in data and len(data['data']) > 0:
                    self.fear_greed_value = int(data['data'][0]['value'])
                    self._last_sentiment_update = current_time
                    logger.info(f"市场恐贪指数更新: {self.fear_greed_value}")
        except Exception as e:
            logger.debug(f"获取市场情绪失败: {e}")
            # 保持默认值50


def main():
    """主函数"""
    import argparse
    import asyncio
    import websockets
    import json

    parser = argparse.ArgumentParser(description='AutoGluon + River 策略 (生产级)')
    parser.add_argument('--train', action='store_true', help='训练所有模型')
    parser.add_argument('--test', action='store_true', help='测试信号生成')
    parser.add_argument('--websocket', action='store_true', help='启动WebSocket服务器模式')
    parser.add_argument('--port', type=int, default=8765, help='WebSocket端口')
    args = parser.parse_args()

    strategy = AutoGluonRiverStrategy(use_hourly_data=True)

    if args.train:
        logger.info("开始训练所有模型...")
        strategy.retrain_all_models()
    elif args.test:
        logger.info("测试信号生成...")
        signals = strategy.get_all_signals()
        for symbol, signal in signals.items():
            logger.info(f"{symbol}: {signal}")
    elif args.websocket:
        # WebSocket模式：启动WebSocket服务器
        logger.info(f"启动WebSocket服务器模式，端口: {args.port}")
        from websocket_server import MLWebSocketServer

        # 创建WebSocket服务器
        server = MLWebSocketServer(strategy, port=args.port)

        # 启动服务器
        try:
            asyncio.run(server.start())
        except KeyboardInterrupt:
            logger.info("WebSocket服务器停止")
    else:
        # 默认模式：启动WebSocket服务器并生成信号
        logger.info("启动AutoGluon策略服务（WebSocket模式）...")
        logger.info(f"WebSocket服务器端口: {args.port}")
        logger.info("信号将通过WebSocket推送并输出到日志文件: /tmp/qlib_analyzer.log")

        # 导入WebSocket服务器
        from websocket_server import MLWebSocketServer

        # 创建WebSocket服务器
        server = MLWebSocketServer(strategy, port=args.port)

        # 在后台线程运行信号生成
        def generate_signals_loop():
            last_retrain_check = 0.0
            while True:
                try:
                    now_ts = time.time()
                    if now_ts - last_retrain_check >= strategy._retrain_check_interval:
                        strategy.check_and_auto_retrain()
                        strategy._last_retrain_check_ts = now_ts
                        last_retrain_check = now_ts

                    # 生成信号
                    signals = strategy.get_all_signals()

                    # 输出有效信号到日志
                    for symbol, signal in signals.items():
                        if signal and signal.get('type') != 'hold':
                            logger.info(f"📊 信号: {symbol} - {signal['type'].upper()} | 置信度: {signal['confidence']:.3f} | 原因: {signal.get('reason', 'N/A')}")

                    # 等待30秒后再次检查
                    time.sleep(30)

                except Exception as e:
                    logger.error(f"生成信号时出错: {e}")
                    time.sleep(5)

        # 启动信号生成线程
        signal_thread = threading.Thread(target=generate_signals_loop, daemon=True)
        signal_thread.start()

        # 启动WebSocket服务器（主线程）
        try:
            asyncio.run(server.start())
        except KeyboardInterrupt:
            logger.info("策略服务停止")


if __name__ == "__main__":
    main()
