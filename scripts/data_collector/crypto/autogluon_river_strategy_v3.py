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
    AutoGluon + River 集成策略 (生产级)
    """

    def __init__(self, use_hourly_data: bool = True):
        self.use_hourly_data = use_hourly_data
        self.symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'SUIUSDT', 'ADAUSDT', 'DOGEUSDT']

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
        self.lookforward = int(os.environ.get('ML_LOOKFORWARD', '24'))
        self.warmup = 50
        self.river_save_interval = int(os.environ.get('RIVER_SAVE_INTERVAL', '20'))  # River模型保存间隔

        # 特征列元数据路径
        self._feature_meta_path = os.path.join(self.model_dir, "_feature_columns.json")

        # 并发控制
        self._training_lock = threading.RLock()
        self._river_lock = threading.RLock()
        self._last_retrain_date = None
        self.enable_auto_retrain = True

        logger.info(f"策略初始化: lookforward={self.lookforward}, warmup={self.warmup}")

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
            'updates_since_save': 0  # 跟踪未保存的更新次数
        }
        logger.info(f"创建新的 {symbol} River模型")

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

            # 转换为datetime对象
            if isinstance(last_dt, pd.Timestamp):
                last_dt = last_dt.to_pydatetime()

            now_utc = datetime.utcnow()
            gap_hours = (now_utc - last_dt.replace(tzinfo=None)).total_seconds() / 3600

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
                start_time = datetime.utcfromtimestamp(last_timestamp / 1000) + step

                if len(batch) < params['limit']:
                    break

                time.sleep(0.1)  # 避免频率限制

            if new_rows:
                new_df = pd.DataFrame(new_rows, columns=[
                    'timestamp', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                    'taker_buy_quote', 'ignore'
                ])

                new_df['date'] = pd.to_datetime(new_df['timestamp'], unit='ms')
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

        # 丢弃前warmup期并去除缺失（不填0）
        f = f.iloc[self.warmup:].replace([np.inf, -np.inf], np.nan).dropna()

        return f

    def _create_labels(self, df: pd.DataFrame) -> pd.Series:
        """创建标签（防泄漏）"""
        close = df['close']
        future = close.shift(-self.lookforward)
        ret_fwd = future / close - 1

        # 动态阈值
        vol = close.pct_change().rolling(48).std()
        dyn = (0.25 * vol).clip(lower=0.002)

        label = (ret_fwd > dyn).astype(int)

        # 去掉尾部lookforward行（未来不可见）
        label = label.iloc[:-self.lookforward]

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

            # 分割
            split = int(len(feats) * 0.8)
            train_df = pd.concat([feats.iloc[:split], labels.iloc[:split].rename('label')], axis=1)
            test_df = pd.concat([feats.iloc[split:], labels.iloc[split:].rename('label')], axis=1)

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
            )

            predictor.fit(
                train_data=train_df,
                time_limit=180,
                presets='medium_quality_faster_train',
                verbosity=1,
                random_seed=42  # 添加随机种子确保可重复性
            )

            self.autogluon_models[symbol] = predictor

            # 评估（修复dict取值）
            perf = predictor.evaluate(test_df, silent=True)
            auc = perf.get('roc_auc', 0.5)
            acc = perf.get('accuracy', 0.5)
            logger.info(f"{symbol} 测试性能: AUC={auc:.4f}, ACC={acc:.4f}, 测试集大小={len(test_df)}")

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

    def generate_signal(self, symbol: str) -> Optional[Dict]:
        """生成交易信号（修正版）"""
        start_time = time.time()
        try:
            df = self._load_data(symbol)
            if len(df) < 300:
                return None

            df = df.sort_values('date').reset_index(drop=True)

            # 过滤未收盘Bar
            last_open = df['date'].iloc[-1]
            now_utc = datetime.utcnow()
            interval_sec = 3600 if self.use_hourly_data else 86400

            if isinstance(last_open, pd.Timestamp):
                last_open = last_open.to_pydatetime()

            if (now_utc - last_open.replace(tzinfo=None)).total_seconds() < interval_sec - 60:
                df = df.iloc[:-1]  # 去掉当前未完成的Bar

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
                return None

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

            # 正确的置信度计算
            confidence = abs(adjusted_buy_prob - 0.5) * 2  # 归一化到0~1

            # 死区和置信度判定（修正）
            if confidence < self.dead_zone:
                rec = 'HOLD'
                reason = f"死区 | p={adjusted_buy_prob:.3f}"
            elif confidence < self.min_confidence:
                rec = 'HOLD'
                reason = f"置信度不足 | c={confidence:.3f}"
            else:
                rec = 'BUY' if adjusted_buy_prob > 0.5 else 'SELL'
                reason = f"{rec} | raw={raw_buy_prob:.3f} adj={adjusted_buy_prob:.3f}"

            # 增量在线更新
            self._update_river_incremental(symbol, df_align, feats)

            # 性能记录
            elapsed = time.time() - start_time
            logger.debug(f"{symbol} 信号生成耗时: {elapsed:.3f}秒")

            return {
                'symbol': symbol,
                'type': rec.lower(),
                'recommendation': rec,
                'buy_prob': round(adjusted_buy_prob, 4),
                'raw_buy_prob': round(raw_buy_prob, 4),
                'confidence': round(confidence, 4),
                'price': float(close),
                'models_used': len(buy_probs),
                'timestamp': datetime.utcnow().isoformat(),
                'reason': reason,
                'source': 'autogluon_river_fixed'
            }

        except Exception as e:
            logger.error(f"{symbol} 信号生成失败: {e}")
            return None

    def retrain_all_models(self):
        """重训所有模型"""
        with self._training_lock:
            logger.info("开始重训所有模型...")
            for symbol in self.symbols:
                self.train_autogluon_model(symbol)
            logger.info("模型重训完成")

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
            start_time = end_time - (365 * 4 * 24 * 60 * 60 * 1000)  # 4年

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
                start_time = data[-1][0] + 1
                time.sleep(0.1)

            if all_data:
                df = pd.DataFrame(all_data, columns=[
                    'timestamp', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                    'taker_buy_quote', 'ignore'
                ])

                df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
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


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='AutoGluon + River 策略 (生产级)')
    parser.add_argument('--train', action='store_true', help='训练所有模型')
    parser.add_argument('--test', action='store_true', help='测试信号生成')
    args = parser.parse_args()

    strategy = AutoGluonRiverStrategy(use_hourly_data=True)

    if args.train:
        logger.info("开始训练所有模型...")
        strategy.retrain_all_models()

    if args.test:
        logger.info("测试信号生成...")
        signals = strategy.get_all_signals()
        for symbol, signal in signals.items():
            logger.info(f"{symbol}: {signal}")


if __name__ == "__main__":
    main()