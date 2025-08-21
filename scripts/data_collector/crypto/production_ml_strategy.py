#!/usr/bin/env python3
"""
增强版生产级ML策略
- 修复回测bug
- 改进标签生成
- 处理不平衡数据
- 添加市场情绪
- 纸上交易系统
"""

import os
import sys
import json
import time
import logging
import warnings
import threading
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from http.server import HTTPServer, BaseHTTPRequestHandler
import numpy as np
import pandas as pd

# 机器学习库
from sklearn.model_selection import train_test_split, TimeSeriesSplit
from sklearn.preprocessing import StandardScaler, RobustScaler
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.utils.class_weight import compute_class_weight
import joblib

# 不平衡数据处理
try:
    from imblearn.over_sampling import SMOTE
    from imblearn.under_sampling import RandomUnderSampler
    from imblearn.combine import SMOTEENN
    IMBLEARN_AVAILABLE = True
except ImportError:
    IMBLEARN_AVAILABLE = False
    print("Installing imblearn for balanced data handling...")
    os.system("pip install imbalanced-learn")
    try:
        from imblearn.over_sampling import SMOTE
        from imblearn.under_sampling import RandomUnderSampler
        from imblearn.combine import SMOTEENN
        IMBLEARN_AVAILABLE = True
    except:
        pass

# XGBoost和LightGBM
try:
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False

try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False

warnings.filterwarnings('ignore')

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/enhanced_production_ml.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class EnhancedProductionML:
    """增强版生产级ML策略"""
    
    def __init__(self, 
                 data_dir: str = "~/.qlib/binance_simple_data",
                 hourly_data_dir: str = "~/.qlib/binance_hourly_data",
                 model_dir: str = "~/.qlib/production_ml_models",
                 symbols: Optional[List[str]] = None,
                 use_hourly_data: bool = False,
                 enable_auto_retrain: bool = True):
        """
        初始化增强版ML策略
        """
        self.use_hourly_data = use_hourly_data
        self.data_dir = os.path.expanduser(hourly_data_dir if use_hourly_data else data_dir)
        self.hourly_data_dir = os.path.expanduser(hourly_data_dir)
        self.model_dir = os.path.expanduser(model_dir)
        
        # 从环境变量读取交易对，如果没有则使用默认值
        if symbols:
            self.symbols = symbols
        else:
            # 从环境变量读取，支持多种格式
            env_symbols = os.getenv('QLIB_WATCH_SYMBOLS', '')
            if not env_symbols:
                env_symbols = os.getenv('STRATEGY_SYMBOLS', '')
            
            if env_symbols:
                # 处理OKX格式（BTC-USDT-SWAP）转换为Binance格式（BTCUSDT）
                symbols_list = []
                for symbol in env_symbols.split(','):
                    symbol = symbol.strip()
                    # 转换 XXX-USDT-SWAP 为 XXXUSDT
                    if '-USDT-SWAP' in symbol:
                        symbol = symbol.replace('-USDT-SWAP', 'USDT')
                        symbol = symbol.replace('-', '')
                    # 确保是USDT结尾
                    if not symbol.endswith('USDT'):
                        symbol = symbol + 'USDT'
                    symbols_list.append(symbol)
                self.symbols = symbols_list
                logger.info(f"从环境变量加载交易对: {self.symbols}")
            else:
                # 使用默认值
                self.symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'SUIUSDT', 'ADAUSDT']
                logger.info(f"使用默认交易对: {self.symbols}")
        
        # 模型配置
        self.models = {}
        self.scalers = {}
        self.label_encoders = {}
        self.selected_features = {}  # 保存选择的特征
        
        # 性能指标
        self.model_metrics = {}
        self.backtest_results = {}
        self.paper_trades = []  # 纸上交易记录
        
        # 市场情绪数据
        self.sentiment_data = {}
        
        # 数据缓存(避免重复加载)
        self._data_cache = {}
        self._cache_timestamp = {}
        
        # 训练锁 - 避免训练时与策略执行冲突
        self._training_lock = threading.RLock()
        self._is_training = False
        self.enable_auto_retrain = enable_auto_retrain
        self._last_retrain_date = None
        
        # 参数配置 - 从环境变量读取
        ml_env = os.getenv('ML_ENVIRONMENT', 'production')
        
        # 根据环境选择配置
        if ml_env == 'development':
            # 开发环境：使用更激进的参数
            up_percentile = int(os.getenv('ML_DEV_UP_PERCENTILE', '65'))
            down_percentile = int(os.getenv('ML_DEV_DOWN_PERCENTILE', '35'))
            min_move = float(os.getenv('ML_DEV_MIN_MOVE', '0.001'))
        else:
            # 生产/staging环境：使用保守参数
            up_percentile = int(os.getenv('ML_UP_PERCENTILE', '75'))
            down_percentile = int(os.getenv('ML_DOWN_PERCENTILE', '25'))
            min_move = float(os.getenv('ML_MIN_MOVE', '0.002'))
        
        self.config = {
            'min_data_points': 500,  # 降低要求以支持新币种如SUI
            'test_size': float(os.getenv('ML_TEST_RATIO', '0.2')),
            'validation_ratio': float(os.getenv('ML_VALIDATION_RATIO', '0.1')),
            'n_features': 60,  # 增加特征数量
            'prediction_horizon': 1,
            
            # 标签生成策略 - 从环境变量读取
            'label_strategy': os.getenv('ML_LABEL_STRATEGY', 'adaptive'),
            'up_threshold': float(os.getenv('ML_UP_THRESHOLD', '0.004')),  # adaptive策略参数
            'down_threshold': float(os.getenv('ML_DOWN_THRESHOLD', '-0.004')),
            'up_percentile': up_percentile,  # percentile策略参数
            'down_percentile': down_percentile,
            'min_move': min_move,  # 最小移动阈值
            'volatility_window': int(os.getenv('ML_VOLATILITY_WINDOW', '20')),
            
            # 二分类配置
            'use_binary_classification': os.getenv('ML_USE_BINARY_CLASSIFICATION', 'true').lower() == 'true',
            
            # 不平衡数据处理
            'handle_imbalance': True,
            'imbalance_strategy': 'smote',  # smote/undersample/combine
            
            # 纸上交易
            'paper_trading': True,
            'paper_balance': 10000,  # 初始资金
            'paper_fee': 0.001,  # 手续费0.1%
            
            # 风控参数
            'max_position_pct': 0.2,  # 最大仓位20%
            'stop_loss': 0.03,  # 止损3%
            'take_profit': 0.08,  # 止盈8%
            'min_confidence': 0.6,  # 最小置信度
            
            # 性能阈值
            'min_accuracy': float(os.getenv('ML_MIN_ACCURACY', '0.55')),
            'min_f1_score': float(os.getenv('ML_MIN_F1_SCORE', '0.45')),
            'fallback_to_technical': os.getenv('ML_FALLBACK_TO_TECHNICAL', 'true').lower() == 'true',
            
            # 环境信息
            'environment': ml_env
        }
        
        logger.info(f"ML环境: {ml_env}")
        logger.info(f"标签策略: {self.config['label_strategy']}")
        logger.info(f"分类模式: {'二分类' if self.config['use_binary_classification'] else '三分类'}")
        if self.config['label_strategy'] == 'percentile':
            logger.info(f"百分位阈值: UP={up_percentile}%, DOWN={down_percentile}%, MIN_MOVE={min_move:.3f}")
        elif self.config['label_strategy'] == 'adaptive':
            logger.info(f"自适应阈值: UP={self.config['up_threshold']:.3f}, DOWN={self.config['down_threshold']:.3f}")
        
        # 创建目录
        os.makedirs(self.model_dir, exist_ok=True)
        os.makedirs(self.hourly_data_dir, exist_ok=True)
        
        # 初始化模型
        self._initialize_models()
        
        # 获取市场情绪
        self._update_market_sentiment()
        
        logger.info(f"增强版ML策略初始化完成")
    
    def _ensure_data_availability(self):
        """确保所有币种的历史数据可用，如果缺失则自动下载"""
        for symbol in self.symbols:
            data_path = os.path.join(self.data_dir, f"{symbol}.csv")
            if not os.path.exists(data_path):
                logger.info(f"检测到 {symbol} 历史数据缺失，开始自动下载...")
                if self._download_symbol_data(symbol):
                    logger.info(f"✅ {symbol} 历史数据下载成功")
                else:
                    logger.warning(f"❌ {symbol} 历史数据下载失败，该币种将被跳过")
                    
    def _download_symbol_data(self, symbol: str) -> bool:
        """下载指定币种的历史数据"""
        try:
            import requests
            
            # 特殊处理新币种的上线时间
            start_dates = {
                'SUIUSDT': '2023-05-03',  # SUI 2023年5月上线
                'APTUSDT': '2022-10-19',  # APT 2022年10月上线
                'ARBUSDT': '2023-03-23',  # ARB 2023年3月上线
                'OPUSDT': '2022-06-01',   # OP 2022年6月上线
            }
            
            start_date = start_dates.get(symbol, '2020-01-01')
            end_date = datetime.now().strftime('%Y-%m-%d')
            
            url = "https://api.binance.com/api/v3/klines"
            params = {
                'symbol': symbol,
                'interval': '1d',
                'startTime': int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000),
                'endTime': int(datetime.now().timestamp() * 1000),
                'limit': 1000
            }
            
            # 使用代理
            proxies = {}
            http_proxy = os.environ.get('http_proxy')
            if http_proxy:
                proxies = {'http': http_proxy, 'https': http_proxy}
            
            response = requests.get(url, params=params, proxies=proxies, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data:
                df = pd.DataFrame(data, columns=[
                    'timestamp', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                    'taker_buy_quote', 'ignore'
                ])
                
                df['date'] = pd.to_datetime(df['timestamp'], unit='ms').dt.strftime('%Y-%m-%d')
                df = df[['date', 'open', 'high', 'low', 'close', 'volume']]
                
                # 转换为float
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = df[col].astype(float)
                
                # 保存到数据目录
                save_path = os.path.join(self.data_dir, f"{symbol}.csv")
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                df.to_csv(save_path, index=False)
                
                logger.info(f"{symbol} 数据下载成功，共{len(df)}条记录")
                return True
            else:
                logger.warning(f"{symbol} 没有获取到数据")
                return False
                
        except Exception as e:
            logger.error(f"下载 {symbol} 数据失败: {e}")
            return False
    
    def _initialize_models(self):
        """初始化或加载模型"""
        # 首先检查并下载缺失的数据
        self._ensure_data_availability()
        
        for symbol in self.symbols:
            model_path = os.path.join(self.model_dir, f"{symbol}_enhanced.pkl")
            
            if os.path.exists(model_path):
                try:
                    self.models[symbol] = joblib.load(model_path)
                    self.scalers[symbol] = joblib.load(
                        os.path.join(self.model_dir, f"{symbol}_scaler.pkl")
                    )
                    
                    # 加载选择的特征
                    features_path = os.path.join(self.model_dir, f"{symbol}_features.pkl")
                    if os.path.exists(features_path):
                        self.selected_features[symbol] = joblib.load(features_path)
                    
                    # 加载指标
                    metrics_path = os.path.join(self.model_dir, f"{symbol}_metrics.json")
                    if os.path.exists(metrics_path):
                        with open(metrics_path, 'r') as f:
                            self.model_metrics[symbol] = json.load(f)
                    
                    logger.info(f"加载 {symbol} 模型，准确率: {self.model_metrics.get(symbol, {}).get('accuracy', 0):.2%}")
                except Exception as e:
                    logger.error(f"加载模型失败 {symbol}: {e}")
                    self._train_model(symbol)
            else:
                self._train_model(symbol)
    
    def _calculate_rsi(self, prices, period=14):
        """计算RSI指标"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _fetch_latest_klines(self, symbol: str, use_hourly: bool = False, last_timestamp: float = None) -> pd.DataFrame:
        """获取最新的K线数据，根据最后更新时间智能决定获取数量"""
        import requests
        
        try:
            # Binance API endpoint
            url = "https://api.binance.com/api/v3/klines"
            
            # 设置参数
            interval = "1h" if use_hourly else "1d"
            
            # 智能计算需要获取的数据量
            limit = 100  # 默认100条
            if last_timestamp:
                # 计算时间差
                time_diff = time.time() - last_timestamp
                if use_hourly:
                    # 小时数据：每小时1条
                    hours_diff = time_diff / 3600
                    limit = min(1000, max(100, int(hours_diff) + 24))
                else:
                    # 日线数据：每天1条  
                    days_diff = time_diff / 86400
                    limit = min(1000, max(100, int(days_diff) + 10))
                    
                if limit > 100:
                    logger.info(f"{symbol} 需要获取{limit}条最新数据")
            
            params = {
                "symbol": symbol,
                "interval": interval,
                "limit": limit
            }
            
            # 发送请求
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            klines = response.json()
            
            # 转换为DataFrame
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            # 转换数据类型
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df['date'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S') if use_hourly else df['timestamp'].dt.strftime('%Y-%m-%d')
            
            # 转换为数值类型
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 只保留需要的列
            df = df[['timestamp', 'date', 'open', 'high', 'low', 'close', 'volume']]
            
            return df
            
        except Exception as e:
            logger.error(f"获取最新K线失败: {e}")
            return pd.DataFrame()
    
    def _load_data(self, symbol: str, use_hourly: bool = None) -> pd.DataFrame:
        """
        加载数据（支持小时数据和实时更新）
        """
        if use_hourly is None:
            use_hourly = self.use_hourly_data
        
        # 缓存时间改为1分钟，以便更频繁地获取最新数据
        cache_key = f"{symbol}_{use_hourly}"
        if cache_key in self._data_cache:
            if time.time() - self._cache_timestamp.get(cache_key, 0) < 60:  # 1分钟缓存
                return self._data_cache[cache_key].copy()
            
        if use_hourly:
            # 尝试加载小时数据
            file_path = os.path.join(self.hourly_data_dir, f"{symbol}.csv")
            if not os.path.exists(file_path):
                # 尝试其他可能的文件名
                file_path = os.path.join(self.hourly_data_dir, f"{symbol}_1h.csv")
            
            if not os.path.exists(file_path):
                logger.warning(f"小时数据不存在: {file_path}")
                logger.info(f"回退到日线数据: {symbol}")
                # 回退到日线数据
                file_path = os.path.join(self.data_dir, f"{symbol}.csv")
                if not os.path.exists(file_path):
                    file_path = os.path.join(self.data_dir, f"{symbol}_1d.csv")
            else:
                logger.debug(f"使用小时数据: {symbol}")
        else:
            # 使用日线数据
            file_path = os.path.join(self.data_dir, f"{symbol}.csv")
            if not os.path.exists(file_path):
                file_path = os.path.join(self.data_dir, f"{symbol}_1d.csv")
                
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"数据文件不存在: {file_path}")
            
        df = pd.read_csv(file_path)
        
        # 尝试获取最新的实时数据
        try:
            # 获取最后数据的时间戳
            last_timestamp = None
            if 'date' in df.columns and len(df) > 0:
                try:
                    last_date = pd.to_datetime(df['date'].iloc[-1])
                    last_timestamp = last_date.timestamp()  # 转换为秒
                except Exception as e:
                    logger.debug(f"转换时间戳失败: {e}")
                    pass  # 如果转换失败，使用None
            
            latest_data = self._fetch_latest_klines(symbol, use_hourly, last_timestamp)
            if latest_data is not None and not latest_data.empty:
                # 确保历史数据有timestamp列
                if 'timestamp' not in df.columns and 'date' in df.columns:
                    df['timestamp'] = pd.to_datetime(df['date'])
                
                # 合并历史数据和最新数据
                df = pd.concat([df, latest_data], ignore_index=True)
                
                # 使用date列去重（因为它是统一格式的字符串）
                if 'date' in df.columns:
                    df = df.drop_duplicates(subset=['date'], keep='last')
                    df = df.sort_values('date').reset_index(drop=True)
                else:
                    df = df.drop_duplicates(subset=['timestamp'], keep='last')
                    df = df.sort_values('timestamp').reset_index(drop=True)
                    
                logger.info(f"已更新 {symbol} 的最新数据，新增 {len(latest_data)} 条记录")
                
                # 定期保存更新的数据到CSV（每小时保存一次）
                save_key = f"{symbol}_last_save"
                if save_key not in self._cache_timestamp or \
                   time.time() - self._cache_timestamp.get(save_key, 0) > 3600:
                    df.to_csv(file_path, index=False)
                    self._cache_timestamp[save_key] = time.time()
                    logger.info(f"已保存 {symbol} 的更新数据到文件")
        except Exception as e:
            logger.warning(f"获取最新数据失败: {e}")
        
        # 标准化列名
        df.columns = [col.lower() for col in df.columns]
        
        # 处理时间 - 使用更灵活的解析
        if 'date' in df.columns:
            # 尝试多种格式解析日期
            try:
                df['date'] = pd.to_datetime(df['date'], format='mixed')
            except:
                try:
                    df['date'] = pd.to_datetime(df['date'], infer_datetime_format=True)
                except:
                    df['date'] = pd.to_datetime(df['date'], errors='coerce')
            df.set_index('date', inplace=True)
        elif 'timestamp' in df.columns:
            try:
                df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed')
            except:
                try:
                    df['timestamp'] = pd.to_datetime(df['timestamp'], infer_datetime_format=True)
                except:
                    df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
            df.set_index('timestamp', inplace=True)
        
        # 更新缓存
        self._data_cache[cache_key] = df.copy()
        self._cache_timestamp[cache_key] = time.time()
        
        df.sort_index(inplace=True)
        
        logger.debug(f"加载 {symbol} 数据: {len(df)} 条记录")
        return df
    
    def _download_hourly_data(self, symbol: str):
        """下载小时数据（2年完整数据）"""
        try:
            import requests
            from datetime import datetime, timedelta
            import time
            
            logger.info(f"正在下载 {symbol} 小时数据...")
            
            # 计算时间范围：从2023年1月1日开始（约2年数据）
            end_date = datetime.now()
            start_date = datetime(2023, 1, 1)  # 从2023年开始，数据更充分
            
            # 特殊处理新币种的上线时间
            special_start_dates = {
                'SUIUSDT': datetime(2023, 5, 3),  # SUI 2023年5月上线
                'APTUSDT': datetime(2022, 10, 19),  # APT 2022年10月上线
                'ARBUSDT': datetime(2023, 3, 23),  # ARB 2023年3月上线
                'OPUSDT': datetime(2022, 6, 1),   # OP 2022年6月上线
            }
            
            if symbol in special_start_dates:
                start_date = max(start_date, special_start_dates[symbol])
            
            # Binance API
            url = "https://api.binance.com/api/v3/klines"
            all_data = []
            
            # 每次获取1000条（约41天的小时数据）
            batch_size = 1000  # Binance限制每次最多1000条
            current_start = start_date
            
            logger.info(f"开始下载 {symbol} 从 {start_date} 到 {end_date} 的小时数据...")
            batch_count = 0
            
            while current_start < end_date:
                # 计算批次结束时间
                current_end = min(current_start + timedelta(hours=batch_size-1), end_date)
                
                params = {
                    'symbol': symbol,
                    'interval': '1h',
                    'startTime': int(current_start.timestamp() * 1000),
                    'endTime': int(current_end.timestamp() * 1000),
                    'limit': batch_size
                }
                
                # 使用代理
                proxies = {}
                http_proxy = os.environ.get('http_proxy')
                if http_proxy:
                    proxies = {'http': http_proxy, 'https': http_proxy}
                
                try:
                    response = requests.get(url, params=params, proxies=proxies, timeout=30)
                    response.raise_for_status()
                    data = response.json()
                    
                    if data:
                        all_data.extend(data)
                        batch_count += 1
                        logger.info(f"  批次{batch_count}: 获取 {len(data)} 条记录 ({current_start.strftime('%Y-%m-%d %H:%M')} - {current_end.strftime('%Y-%m-%d %H:%M')})")
                        
                        # 从最后一条数据的时间戳+1小时开始下一批次（避免重复）
                        last_timestamp = data[-1][0]
                        current_start = datetime.fromtimestamp(last_timestamp/1000) + timedelta(hours=1)
                    else:
                        logger.info(f"  批次{batch_count+1}: 无数据")
                        break
                    
                    time.sleep(0.2)  # 避免频率限制
                    
                except Exception as e:
                    logger.warning(f"  批次下载失败: {e}，跳过...")
                    current_start = current_end
                    continue
            
            if not all_data:
                logger.error(f"{symbol} 没有获取到数据")
                return False
            
            # 转换为DataFrame
            df = pd.DataFrame(all_data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df[['date', 'open', 'high', 'low', 'close', 'volume']]
            
            # 转换为float
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            
            # 去重并排序
            df = df.drop_duplicates(subset=['date'])
            df = df.sort_values('date')
            
            # 保存到小时数据目录
            save_path = os.path.join(self.hourly_data_dir, f"{symbol}.csv")
            os.makedirs(self.hourly_data_dir, exist_ok=True)
            df.to_csv(save_path, index=False)
            
            logger.info(f"✅ {symbol} 小时数据下载成功，共 {len(df)} 条记录，保存到 {save_path}")
            return True
            
        except Exception as e:
            logger.error(f"下载 {symbol} 小时数据失败: {e}")
            return False
    
    def _update_market_sentiment(self):
        """获取市场情绪指标"""
        try:
            # 恐贪指数API（示例）
            response = requests.get(
                "https://api.alternative.me/fng/",
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                if 'data' in data and len(data['data']) > 0:
                    self.sentiment_data['fear_greed'] = {
                        'value': int(data['data'][0]['value']),
                        'classification': data['data'][0]['value_classification']
                    }
                    logger.info(f"恐贪指数: {self.sentiment_data['fear_greed']}")
        except Exception as e:
            logger.warning(f"获取市场情绪失败: {e}")
            self.sentiment_data['fear_greed'] = {'value': 50, 'classification': 'Neutral'}
    
    def _create_enhanced_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        创建增强特征（包含市场情绪）
        """
        features = pd.DataFrame(index=df.index)
        
        # 基础特征
        features['returns'] = df['close'].pct_change()
        features['log_returns'] = np.log(df['close'] / df['close'].shift(1))
        features['price_change'] = df['close'] - df['close'].shift(1)
        
        # 价格特征
        features['hl_ratio'] = (df['high'] - df['low']) / df['close']
        features['hc_ratio'] = (df['high'] - df['close']) / df['close']
        features['cl_ratio'] = (df['close'] - df['low']) / df['close']
        features['oc_ratio'] = (df['close'] - df['open']) / df['open']
        
        # 成交量特征
        features['volume_ratio'] = df['volume'] / df['volume'].rolling(20).mean()
        features['volume_change'] = df['volume'].pct_change()
        features['volume_price'] = df['volume'] * df['close']
        
        # 价格动量
        for period in [3, 5, 10, 20, 30]:
            features[f'momentum_{period}'] = df['close'] / df['close'].shift(period) - 1
            features[f'roc_{period}'] = (df['close'] - df['close'].shift(period)) / df['close'].shift(period)
        
        # 移动平均
        for period in [5, 10, 20, 50, 100]:
            ma = df['close'].rolling(period).mean()
            features[f'ma_{period}'] = ma
            features[f'ma_ratio_{period}'] = df['close'] / ma
            features[f'ma_diff_{period}'] = df['close'] - ma
        
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
        for period in [10, 20]:
            bb_mean = df['close'].rolling(period).mean()
            bb_std = df['close'].rolling(period).std()
            features[f'bb_upper_{period}'] = bb_mean + (bb_std * 2)
            features[f'bb_lower_{period}'] = bb_mean - (bb_std * 2)
            features[f'bb_width_{period}'] = features[f'bb_upper_{period}'] - features[f'bb_lower_{period}']
            features[f'bb_position_{period}'] = (df['close'] - features[f'bb_lower_{period}']) / features[f'bb_width_{period}']
        
        # ATR
        for period in [7, 14]:
            features[f'atr_{period}'] = self._calculate_atr(df, period)
        
        # 波动率
        for period in [5, 10, 20]:
            features[f'volatility_{period}'] = df['close'].pct_change().rolling(period).std()
            features[f'volatility_ratio_{period}'] = features[f'volatility_{period}'] / features[f'volatility_{period}'].rolling(50).mean()
        
        # 市场微结构
        features['spread'] = (df['high'] - df['low']) / df['close']
        features['spread_ma'] = features['spread'].rolling(20).mean()
        
        # 成交量分析
        features['obv'] = (np.sign(df['close'].diff()) * df['volume']).cumsum()
        features['vwap'] = (df['volume'] * (df['high'] + df['low'] + df['close']) / 3).cumsum() / df['volume'].cumsum()
        
        # 市场情绪特征（新增）
        if self.sentiment_data.get('fear_greed'):
            fear_greed_value = self.sentiment_data['fear_greed']['value']
            features['fear_greed'] = fear_greed_value
            features['sentiment_extreme'] = abs(fear_greed_value - 50) / 50  # 0-1范围
            features['sentiment_bullish'] = 1 if fear_greed_value > 50 else 0
            features['sentiment_bearish'] = 1 if fear_greed_value < 50 else 0
        else:
            features['fear_greed'] = 50
            features['sentiment_extreme'] = 0
            features['sentiment_bullish'] = 0
            features['sentiment_bearish'] = 0
        
        # 时间特征
        features['day_of_week'] = df.index.dayofweek
        features['month'] = df.index.month
        features['quarter'] = df.index.quarter
        
        # 滞后特征
        for i in range(1, 8):
            features[f'returns_lag_{i}'] = features['returns'].shift(i)
            features[f'volume_lag_{i}'] = features['volume_ratio'].shift(i)
        
        # 滚动统计
        for window in [5, 10, 20]:
            features[f'returns_mean_{window}'] = features['returns'].rolling(window).mean()
            features[f'returns_std_{window}'] = features['returns'].rolling(window).std()
            features[f'returns_skew_{window}'] = features['returns'].rolling(window).skew()
            features[f'returns_kurt_{window}'] = features['returns'].rolling(window).kurt()
        
        # 清理数据：替换无穷大值和限制极端值
        features = features.replace([np.inf, -np.inf], np.nan)
        
        # 对于每一列，限制到合理范围内（99.9百分位）
        for col in features.columns:
            if features[col].dtype in [np.float64, np.float32]:
                # 计算非NaN值的百分位
                lower = features[col].quantile(0.001)
                upper = features[col].quantile(0.999)
                if not np.isnan(lower) and not np.isnan(upper):
                    features[col] = features[col].clip(lower, upper)
        
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
    
    def _create_improved_labels(self, df: pd.DataFrame, features: pd.DataFrame) -> pd.Series:
        """
        改进的标签生成策略 - 支持二分类和三分类
        """
        future_returns = df['close'].shift(-self.config['prediction_horizon']) / df['close'] - 1
        
        # 使用二分类配置
        use_binary = self.config.get('use_binary_classification', True)
        
        if use_binary:
            # 二分类：只有BUY(1)和SELL(0)
            if self.config['label_strategy'] == 'adaptive':
                # 使用0作为分界点
                threshold = 0.0
            elif self.config['label_strategy'] == 'volatility_adjusted':
                # 基于波动率的动态阈值，但使用0作为中心
                volatility = df['close'].pct_change().rolling(self.config['volatility_window']).std()
                threshold = 0.0  # 二分类使用0作为分界
            else:  # percentile
                # 使用中位数作为分界点
                threshold = np.median(future_returns.dropna())
            
            # 创建二分类标签
            labels = pd.Series(index=df.index, dtype=int)
            labels[future_returns > threshold] = 1  # BUY
            labels[future_returns <= threshold] = 0  # SELL
            
            # 统计标签分布
            label_counts = labels.value_counts()
            logger.info(f"二分类标签分布: SELL={label_counts.get(0, 0)}, BUY={label_counts.get(1, 0)}")
            
        else:
            # 三分类（原有逻辑）
            if self.config['label_strategy'] == 'adaptive':
                # 自适应阈值：使用固定阈值
                up_threshold = self.config['up_threshold']
                down_threshold = self.config['down_threshold']
                
                # 确保阈值合理
                if up_threshold <= 0:
                    up_threshold = 0.004  # 默认0.4%
                if down_threshold >= 0:
                    down_threshold = -0.004  # 默认-0.4%
                
            elif self.config['label_strategy'] == 'volatility_adjusted':
                # 基于波动率的动态阈值
                volatility = df['close'].pct_change().rolling(self.config['volatility_window']).std()
                mean_vol = volatility.mean()
                up_threshold = mean_vol * 1.0  # 1倍标准差
                down_threshold = -mean_vol * 1.0
                
                # 应用最小移动阈值
                up_threshold = max(up_threshold, self.config['min_move'])
                down_threshold = min(down_threshold, -self.config['min_move'])
                
            else:  # percentile
                # 使用历史百分位
                up_threshold = np.percentile(future_returns.dropna(), self.config['up_percentile'])
                down_threshold = np.percentile(future_returns.dropna(), self.config['down_percentile'])
                
                # 应用最小移动阈值
                if abs(up_threshold) < self.config['min_move']:
                    up_threshold = self.config['min_move']
                if abs(down_threshold) < self.config['min_move']:
                    down_threshold = -self.config['min_move']
            
            # 创建标签
            labels = pd.Series(index=df.index, dtype=int)
            
            # 处理阈值是Series的情况
            if isinstance(up_threshold, pd.Series):
                for i in df.index:
                    if i in future_returns.index and i in up_threshold.index:
                        if future_returns[i] > up_threshold[i]:
                            labels[i] = 2  # 上涨
                        elif future_returns[i] < down_threshold[i]:
                            labels[i] = 0  # 下跌
                        else:
                            labels[i] = 1  # 横盘
            else:
                labels[future_returns > up_threshold] = 2  # 上涨
                labels[future_returns < down_threshold] = 0  # 下跌
                labels[(future_returns >= down_threshold) & (future_returns <= up_threshold)] = 1  # 横盘
            
            # 统计标签分布
            label_counts = labels.value_counts()
            logger.info(f"三分类标签分布: 下跌={label_counts.get(0, 0)}, 横盘={label_counts.get(1, 0)}, 上涨={label_counts.get(2, 0)}")
        
        return labels
    
    def _handle_imbalanced_data(self, X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        处理不平衡数据
        """
        if not self.config['handle_imbalance'] or not IMBLEARN_AVAILABLE:
            return X, y
        
        strategy = self.config['imbalance_strategy']
        
        try:
            if strategy == 'smote':
                # SMOTE过采样
                smote = SMOTE(random_state=42)
                X_balanced, y_balanced = smote.fit_resample(X, y)
                logger.info(f"SMOTE平衡后: {len(y_balanced)} 样本")
                
            elif strategy == 'undersample':
                # 欠采样
                rus = RandomUnderSampler(random_state=42)
                X_balanced, y_balanced = rus.fit_resample(X, y)
                logger.info(f"欠采样后: {len(y_balanced)} 样本")
                
            elif strategy == 'combine':
                # 结合过采样和欠采样
                sme = SMOTEENN(random_state=42)
                X_balanced, y_balanced = sme.fit_resample(X, y)
                logger.info(f"SMOTEENN平衡后: {len(y_balanced)} 样本")
                
            else:
                X_balanced, y_balanced = X, y
            
            # 显示平衡后的分布
            unique, counts = np.unique(y_balanced, return_counts=True)
            logger.info(f"平衡后分布: {dict(zip(unique, counts))}")
            
            return X_balanced, y_balanced
            
        except Exception as e:
            logger.warning(f"数据平衡失败: {e}")
            return X, y
    
    def _train_model(self, symbol: str):
        """
        训练模型（改进版）
        """
        logger.info(f"开始训练 {symbol} 增强模型...")
        
        # 加载数据
        df = self._load_data(symbol)
        if len(df) < self.config['min_data_points']:
            logger.warning(f"{symbol} 数据不足")
            return
        
        # 创建特征
        features = self._create_enhanced_features(df)
        
        # 创建标签（改进的策略）
        labels = self._create_improved_labels(df, features)
        
        # 删除NaN
        valid_idx = ~(features.isna().any(axis=1) | labels.isna())
        features = features[valid_idx]
        labels = labels[valid_idx]
        
        # 特征选择（保留前N个重要特征）
        from sklearn.feature_selection import SelectKBest, f_classif
        selector = SelectKBest(f_classif, k=min(self.config['n_features'], features.shape[1]))
        features_selected = selector.fit_transform(features, labels)
        selected_features = features.columns[selector.get_support()].tolist()
        
        # 保存选择的特征
        self.selected_features[symbol] = selected_features
        
        # 时间序列分割
        split_idx = int(len(features_selected) * (1 - self.config['test_size']))
        X_train = features_selected[:split_idx]
        X_test = features_selected[split_idx:]
        y_train = labels[:split_idx].values
        y_test = labels[split_idx:].values
        
        # 处理不平衡数据
        X_train_balanced, y_train_balanced = self._handle_imbalanced_data(X_train, y_train)
        
        # 数据缩放
        scaler = RobustScaler()
        X_train_scaled = scaler.fit_transform(X_train_balanced)
        X_test_scaled = scaler.transform(X_test)
        
        self.scalers[symbol] = scaler
        
        # 计算类权重
        classes = np.unique(y_train_balanced)
        class_weights = compute_class_weight('balanced', classes=classes, y=y_train_balanced)
        class_weight_dict = dict(zip(classes, class_weights))
        
        # 训练多个模型
        models = {}
        scores = {}
        
        # XGBoost
        if XGBOOST_AVAILABLE:
            logger.info("训练XGBoost...")
            xgb_model = xgb.XGBClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.01,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=42,
                scale_pos_weight=class_weights[2] if 2 in class_weights else 1,  # 处理不平衡
                n_jobs=-1
            )
            xgb_model.fit(X_train_scaled, y_train_balanced)
            models['xgboost'] = xgb_model
            scores['xgboost'] = xgb_model.score(X_test_scaled, y_test)
        
        # LightGBM
        if LIGHTGBM_AVAILABLE:
            logger.info("训练LightGBM...")
            lgb_model = lgb.LGBMClassifier(
                n_estimators=200,
                num_leaves=31,
                learning_rate=0.01,
                feature_fraction=0.8,
                bagging_fraction=0.8,
                bagging_freq=5,
                random_state=42,
                class_weight='balanced',  # 自动平衡
                n_jobs=-1
            )
            lgb_model.fit(X_train_scaled, y_train_balanced)
            models['lightgbm'] = lgb_model
            scores['lightgbm'] = lgb_model.score(X_test_scaled, y_test)
        
        # RandomForest
        logger.info("训练RandomForest...")
        rf_model = RandomForestClassifier(
            n_estimators=200,
            max_depth=10,
            min_samples_split=5,
            min_samples_leaf=2,
            class_weight='balanced',  # 处理不平衡
            random_state=42,
            n_jobs=-1
        )
        rf_model.fit(X_train_scaled, y_train_balanced)
        models['rf'] = rf_model
        scores['rf'] = rf_model.score(X_test_scaled, y_test)
        
        # 保存模型
        self.models[symbol] = models
        
        # 集成预测评估
        ensemble_pred = self._ensemble_predict(models, X_test_scaled)
        accuracy = accuracy_score(y_test, ensemble_pred)
        precision = precision_score(y_test, ensemble_pred, average='weighted', zero_division=0)
        recall = recall_score(y_test, ensemble_pred, average='weighted', zero_division=0)
        f1 = f1_score(y_test, ensemble_pred, average='weighted', zero_division=0)
        
        # 保存指标
        self.model_metrics[symbol] = {
            'accuracy': float(accuracy),
            'precision': float(precision),
            'recall': float(recall),
            'f1_score': float(f1),
            'individual_scores': {k: float(v) for k, v in scores.items()},
            'train_samples': len(X_train),
            'test_samples': len(X_test),
            'balanced_samples': len(X_train_balanced),
            'features_used': len(selected_features),
            'label_strategy': self.config['label_strategy'],
            'training_date': datetime.now().isoformat()
        }
        
        logger.info(f"{symbol} 增强模型性能 - 准确率: {accuracy:.4f}, F1: {f1:.4f}")
        
        # 保存模型
        self._save_models(symbol)
    
    def _ensemble_predict(self, models: Dict, X: np.ndarray) -> np.ndarray:
        """集成预测"""
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
        
        ensemble_pred = np.sum(predictions, axis=0)
        return np.round(ensemble_pred).astype(int)
    
    def _ensemble_predict_proba(self, models: Dict, X: np.ndarray) -> np.ndarray:
        """集成预测概率"""
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
        
        return np.sum(probabilities, axis=0)
    
    def _save_models(self, symbol: str):
        """保存模型"""
        try:
            model_path = os.path.join(self.model_dir, f"{symbol}_enhanced.pkl")
            joblib.dump(self.models[symbol], model_path)
            
            scaler_path = os.path.join(self.model_dir, f"{symbol}_scaler.pkl")
            joblib.dump(self.scalers[symbol], scaler_path)
            
            # 保存选择的特征
            features_path = os.path.join(self.model_dir, f"{symbol}_features.pkl")
            if hasattr(self, 'selected_features') and symbol in self.selected_features:
                joblib.dump(self.selected_features[symbol], features_path)
            
            metrics_path = os.path.join(self.model_dir, f"{symbol}_metrics.json")
            with open(metrics_path, 'w') as f:
                json.dump(self.model_metrics[symbol], f, indent=2)
            
            logger.info(f"模型已保存: {symbol}")
        except Exception as e:
            logger.error(f"保存模型失败: {e}")
    
    def backtest_fixed(self, symbol: str, start_date: Optional[str] = None) -> Dict:
        """
        修复的回测系统
        """
        logger.info(f"开始回测 {symbol} (修复版)")
        
        # 加载数据
        df = self._load_data(symbol)
        features = self._create_enhanced_features(df)
        
        # 删除NaN
        valid_idx = ~features.isna().any(axis=1)
        features = features[valid_idx]
        df_valid = df[valid_idx]
        
        if start_date:
            features = features[features.index >= start_date]
            df_valid = df_valid[df_valid.index >= start_date]
        
        if symbol not in self.models or symbol not in self.scalers:
            logger.error(f"没有可用的模型: {symbol}")
            return {}
        
        # 特征选择（必须与训练时一致）
        if hasattr(self, 'selected_features') and symbol in self.selected_features:
            # 使用训练时选择的特征
            logger.info(f"Applying {len(self.selected_features[symbol])} selected features for {symbol}")
            missing_cols = [col for col in self.selected_features[symbol] if col not in features.columns]
            if missing_cols:
                logger.warning(f"Missing features for {symbol}: {missing_cols}")
                # 添加缺失的特征列（用0填充）
                for col in missing_cols:
                    features[col] = 0
            # 只保留训练时选择的特征，并按相同顺序
            features = features[self.selected_features[symbol]]
        else:
            logger.error(f"No selected features found for {symbol}. Has features: {hasattr(self, 'selected_features')}, Keys: {self.selected_features.keys() if hasattr(self, 'selected_features') else 'None'}")
            return None
        
        # 预测
        features_scaled = self.scalers[symbol].transform(features)
        predictions = self._ensemble_predict(self.models[symbol], features_scaled)
        probabilities = self._ensemble_predict_proba(self.models[symbol], features_scaled)
        
        # 生成交易信号
        positions = pd.Series(index=df_valid.index, dtype=float)
        
        # 只在高置信度时交易
        max_prob = np.max(probabilities, axis=1)
        confident_mask = max_prob > self.config['min_confidence']
        
        positions[predictions == 2] = 1.0   # 买入
        positions[predictions == 0] = -1.0  # 卖出
        positions[predictions == 1] = 0.0   # 持有
        
        # 应用置信度过滤
        positions = positions * confident_mask
        positions = positions.fillna(0)
        
        # 计算收益（修复版）
        returns = df_valid['close'].pct_change()
        
        # 考虑手续费
        trade_mask = positions != positions.shift(1)
        fees = trade_mask.astype(float) * self.config['paper_fee']
        
        # 策略收益 = 仓位 * 收益 - 手续费
        strategy_returns = positions.shift(1) * returns - fees
        
        # 累积收益（正确的计算方式）
        cum_returns = (1 + returns).cumprod()
        cum_strategy_returns = (1 + strategy_returns).cumprod()
        
        # 计算指标
        total_return = float(cum_strategy_returns.iloc[-1] - 1)
        buy_hold_return = float(cum_returns.iloc[-1] - 1)
        
        # 夏普比率（年化）
        if strategy_returns.std() > 0:
            sharpe_ratio = strategy_returns.mean() / strategy_returns.std() * np.sqrt(252)
        else:
            sharpe_ratio = 0
        
        # 最大回撤
        rolling_max = cum_strategy_returns.expanding().max()
        drawdown = (cum_strategy_returns - rolling_max) / rolling_max
        max_drawdown = float(drawdown.min())
        
        # 胜率
        winning_trades = (strategy_returns > fees).sum()
        losing_trades = (strategy_returns < -fees).sum()
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
            'avg_confidence': float(max_prob.mean()),
            'model_accuracy': self.model_metrics.get(symbol, {}).get('accuracy', 0)
        }
        
        self.backtest_results[symbol] = backtest_results
        
        logger.info(f"{symbol} 回测结果(修复版):")
        logger.info(f"  策略收益: {total_return:.2%}")
        logger.info(f"  买入持有收益: {buy_hold_return:.2%}")
        logger.info(f"  夏普比率: {sharpe_ratio:.2f}")
        logger.info(f"  最大回撤: {max_drawdown:.2%}")
        logger.info(f"  胜率: {win_rate:.2%}")
        logger.info(f"  平均置信度: {max_prob.mean():.2%}")
        
        return backtest_results
    
    def paper_trade(self, signal: Dict) -> Dict:
        """
        纸上交易系统
        """
        if not self.config['paper_trading']:
            return {}
        
        trade = {
            'timestamp': datetime.now().isoformat(),
            'symbol': signal['symbol'],
            'action': signal['recommendation'],
            'price': signal['price'],
            'confidence': signal['confidence'],
            'position_size': 0,
            'executed': False,
            'reason': ''
        }
        
        # 风险检查
        if signal['confidence'] < self.config['min_confidence']:
            trade['reason'] = f"置信度太低 ({signal['confidence']:.2%})"
            self.paper_trades.append(trade)
            return trade
        
        # 仓位计算
        balance = self.config['paper_balance']
        max_position = balance * self.config['max_position_pct']
        
        if signal['recommendation'] == 'BUY':
            trade['position_size'] = max_position / signal['price']
            trade['executed'] = True
            trade['reason'] = "买入信号执行"
        elif signal['recommendation'] == 'SELL':
            trade['position_size'] = -max_position / signal['price']
            trade['executed'] = True
            trade['reason'] = "卖出信号执行"
        else:
            trade['reason'] = "持有信号"
        
        self.paper_trades.append(trade)
        
        # 只保留最近100条记录
        if len(self.paper_trades) > 100:
            self.paper_trades = self.paper_trades[-100:]
        
        return trade
    
    def generate_signal(self, symbol: str) -> Optional[Dict]:
        """生成交易信号（带锁保护，训练时暂停）"""
        # 如果正在训练，等待训练完成
        with self._training_lock:
            if symbol not in self.models:
                logger.debug(f"No model found for {symbol}")
                return None
            
            if symbol not in self.selected_features:
                logger.warning(f"No selected features for {symbol}, skipping signal generation")
                return None
            
            # 检查模型性能是否达标
            model_metrics = self.model_metrics.get(symbol, {})
            accuracy = model_metrics.get('accuracy', 0)
            f1_score = model_metrics.get('f1_score', 0)
            
            # 如果模型性能低于阈值且配置了回退到技术指标
            if self.config['fallback_to_technical']:
                if accuracy < self.config['min_accuracy'] or f1_score < self.config['min_f1_score']:
                    logger.warning(f"{symbol} 模型性能不达标 (准确率={accuracy:.2%}, F1={f1_score:.3f}), 回退到技术指标策略")
                    return self._generate_technical_signal(symbol)
                
        try:
            # 加载最新数据
            df = self._load_data(symbol)
            if len(df) < 100:
                return None
            
            # 创建特征
            features = self._create_enhanced_features(df)
            
            # 应用特征选择（与训练时一致）
            if symbol in self.selected_features:
                features = features[self.selected_features[symbol]]
            else:
                logger.error(f"Feature selection failed for {symbol}")
                return None
            
            # 获取最新特征
            latest_features = features.dropna().iloc[-1:].values
            
            # 缩放
            latest_features_scaled = self.scalers[symbol].transform(latest_features)
            
            # 预测
            models = self.models[symbol]
            prediction = self._ensemble_predict(models, latest_features_scaled)[0]
            probabilities = self._ensemble_predict_proba(models, latest_features_scaled)[0]
            
            # 根据分类模式映射
            use_binary = self.config.get('use_binary_classification', True)
            if use_binary:
                # 二分类映射
                signal_map = {0: 'SELL', 1: 'BUY'}
                recommendation = signal_map[prediction]
            else:
                # 三分类映射
                signal_map = {0: 'SELL', 1: 'HOLD', 2: 'BUY'}
                recommendation = signal_map[prediction]
            
            # 改进的置信度计算
            # 1. 基础置信度：对应预测类别的概率（而不是最大概率）
            base_confidence = float(probabilities[prediction])
            
            # 2. 决策清晰度：最大概率与次大概率的差值
            sorted_probs = np.sort(probabilities)[::-1]
            if len(sorted_probs) >= 2:
                clarity_score = float(sorted_probs[0] - sorted_probs[1])
            else:
                clarity_score = float(sorted_probs[0])  # 只有一个概率时使用该概率
            
            # 3. 模型一致性：如果有多个模型，检查它们的一致性
            model_agreement = 1.0  # 默认完全一致
            if len(models) > 1:
                predictions = [model.predict(latest_features_scaled)[0] for model in models.values()]
                agreement_rate = predictions.count(prediction) / len(predictions)
                model_agreement = agreement_rate
            
            # 4. 技术指标支持度（基于最新数据）
            technical_support = 0.5  # 默认中性
            if len(df) > 20:
                close_price = df['close'].iloc[-1]
                sma20 = df['close'].rolling(20).mean().iloc[-1]
                rsi = self._calculate_rsi(df['close'], 14).iloc[-1] if len(df) > 14 else 50
                
                if recommendation == 'BUY':
                    if close_price > sma20:
                        technical_support += 0.2
                    if rsi < 30:
                        technical_support += 0.3
                    elif rsi < 50:
                        technical_support += 0.1
                elif recommendation == 'SELL':
                    if close_price < sma20:
                        technical_support += 0.2
                    if rsi > 70:
                        technical_support += 0.3
                    elif rsi > 50:
                        technical_support += 0.1
                else:  # HOLD
                    if 40 < rsi < 60:
                        technical_support += 0.2
            
            # 5. 综合置信度计算（加权平均）
            # 权重分配：基础概率40%，清晰度20%，模型一致性20%，技术支持20%
            confidence = (
                base_confidence * 0.4 +
                clarity_score * 0.2 +
                model_agreement * 0.2 +
                technical_support * 0.2
            )
            
            # 6. 根据市场情绪调整（贪婪时更谨慎，恐慌时更大胆）
            if self.sentiment_data and 'value' in self.sentiment_data:
                sentiment_value = self.sentiment_data['value']
                if sentiment_value > 75:  # 极度贪婪
                    if recommendation == 'BUY':
                        confidence *= 0.9  # 降低买入置信度
                    elif recommendation == 'SELL':
                        confidence *= 1.1  # 提高卖出置信度
                elif sentiment_value < 25:  # 极度恐慌
                    if recommendation == 'BUY':
                        confidence *= 1.1  # 提高买入置信度
                    elif recommendation == 'SELL':
                        confidence *= 0.9  # 降低卖出置信度
            
            # 确保置信度在合理范围内
            confidence = max(0.1, min(0.95, confidence))
            
            # 风险评估
            volatility = float(df['close'].pct_change().rolling(20).std().iloc[-1])
            
            if volatility > 0.05:
                risk_level = 'HIGH'
            elif volatility > 0.02:
                risk_level = 'MEDIUM'
            else:
                risk_level = 'LOW'
            
            # 根据分类模式构建概率信息
            if use_binary:
                ai_prediction = {
                    'direction': recommendation,
                    'probability_sell': float(probabilities[0]),
                    'probability_buy': float(probabilities[1]),
                    'model_type': 'ENHANCED_ENSEMBLE_BINARY',
                    'models_used': list(models.keys())
                }
            else:
                ai_prediction = {
                    'direction': recommendation,
                    'probability_down': float(probabilities[0]),
                    'probability_hold': float(probabilities[1]),
                    'probability_up': float(probabilities[2]),
                    'model_type': 'ENHANCED_ENSEMBLE',
                    'models_used': list(models.keys())
                }
            
            signal = {
                'symbol': symbol,
                'timestamp': datetime.now().isoformat(),
                'recommendation': recommendation,
                'confidence': confidence,
                'price': float(df['close'].iloc[-1]),
                'volume': float(df['volume'].iloc[-1]),
                'ai_prediction': ai_prediction,
                'risk_metrics': {
                    'risk_level': risk_level,
                    'volatility': volatility,
                    'suggested_position_size': max(0.1, min(1.0, 1.0 - volatility * 10))
                },
                'model_metrics': self.model_metrics.get(symbol, {}),
                'sentiment': self.sentiment_data
            }
            
            # 执行纸上交易
            paper_result = self.paper_trade(signal)
            signal['paper_trade'] = paper_result
            
            return signal
            
        except Exception as e:
            logger.error(f"生成信号失败 {symbol}: {e}")
            return None
    
    def _generate_technical_signal(self, symbol: str) -> Optional[Dict]:
        """基于技术指标生成信号（作为ML模型的备用方案）"""
        try:
            # 加载最新数据
            df = self._load_data(symbol)
            if len(df) < 50:
                return None
            
            # 计算技术指标
            df['sma_20'] = df['close'].rolling(20).mean()
            df['sma_50'] = df['close'].rolling(50).mean()
            df['rsi'] = self._calculate_rsi(df['close'], 14)
            
            # 获取最新值
            latest = df.iloc[-1]
            close_price = latest['close']
            sma_20 = latest['sma_20']
            sma_50 = latest['sma_50']
            rsi = latest['rsi']
            
            # 生成信号
            signal_strength = 0
            
            # 移动平均线信号
            if sma_20 > sma_50:
                signal_strength += 1
            else:
                signal_strength -= 1
            
            # 价格相对于MA的位置
            if close_price > sma_20:
                signal_strength += 0.5
            else:
                signal_strength -= 0.5
            
            # RSI信号
            if rsi < 30:
                signal_strength += 1.5  # 超卖
            elif rsi > 70:
                signal_strength -= 1.5  # 超买
            elif rsi < 45:
                signal_strength += 0.5
            elif rsi > 55:
                signal_strength -= 0.5
            
            # 生成推荐
            if signal_strength >= 1.5:
                recommendation = 'BUY'
                confidence = min(0.65 + signal_strength * 0.05, 0.85)
            elif signal_strength <= -1.5:
                recommendation = 'SELL'
                confidence = min(0.65 + abs(signal_strength) * 0.05, 0.85)
            else:
                recommendation = 'HOLD'
                confidence = 0.5 + abs(signal_strength) * 0.1
            
            return {
                'symbol': symbol,
                'recommendation': recommendation,
                'confidence': float(confidence),
                'price': float(close_price),
                'source': 'TECHNICAL',  # 标记为技术指标信号
                'indicators': {
                    'rsi': float(rsi),
                    'sma_20': float(sma_20),
                    'sma_50': float(sma_50),
                    'signal_strength': float(signal_strength)
                },
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"生成技术信号失败 {symbol}: {e}")
            return None
    
    def retrain_all_models(self, force: bool = False):
        """重新训练所有模型（提供别名方法）"""
        return self.retrain_all()
    
    def retrain_all(self):
        """重新训练所有模型（带锁保护）"""
        if self._is_training:
            logger.warning("模型正在训练中，跳过本次训练请求")
            return False
            
        with self._training_lock:
            self._is_training = True
            try:
                logger.info(f"开始重新训练所有增强模型... 币种列表: {self.symbols}")
                
                # 更新市场情绪
                self._update_market_sentiment()
                
                # 训练所有币种
                for i, symbol in enumerate(self.symbols, 1):
                    logger.info(f"训练进度: [{i}/{len(self.symbols)}] 正在训练 {symbol} 模型...")
                    self._train_model(symbol)
                    logger.info(f"✓ {symbol} 模型训练完成")
                    
                self._last_retrain_date = datetime.now()
                logger.info(f"所有模型训练完成 (UTC时间: {datetime.utcnow()})")
                return True
            except Exception as e:
                logger.error(f"模型训练失败: {e}")
                return False
            finally:
                self._is_training = False
    
    def check_and_auto_retrain(self):
        """检查并执行自动重训练（每天UTC 12:00）"""
        if not self.enable_auto_retrain:
            return
            
        now = datetime.utcnow()
        # 检查是否是UTC 12:00 (允许前后30分钟误差，更宽松的时间窗口)
        # 11:30 到 12:30 之间都可以触发
        if (now.hour == 11 and now.minute >= 30) or (now.hour == 12 and now.minute <= 30):
            # 检查今天是否已经训练过
            if self._last_retrain_date is None or \
               self._last_retrain_date.date() < now.date():
                logger.info(f"触发自动重训练 (UTC时间: {now}, 当地时间: {datetime.now()})")
                logger.info(f"上次训练时间: {self._last_retrain_date}")
                # 在新线程中执行训练，避免阻塞主线程
                threading.Thread(target=self.retrain_all, daemon=True).start()
        
        # 每小时输出一次当前UTC时间，方便调试
        if now.minute == 0 and now.second < 30:
            logger.info(f"当前UTC时间: {now.strftime('%Y-%m-%d %H:%M:%S')}, 等待12:00触发重训练")
    
    def get_all_signals(self) -> Dict:
        """获取所有信号"""
        signals = {}
        for symbol in self.symbols:
            signal = self.generate_signal(symbol)
            if signal:
                signals[symbol] = signal
        return signals


class EnhancedMLHTTPHandler(BaseHTTPRequestHandler):
    """HTTP处理器"""
    
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            response = {
                'status': 'ok',
                'service': 'enhanced-production-ml',
                'models_loaded': len(self.server.analyzer.models),
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
                'backtest_results': self.server.analyzer.backtest_results,
                'paper_trades': self.server.analyzer.paper_trades[-10:]  # 最近10条
            }
            self.wfile.write(json.dumps(response).encode())
            
        elif self.path == '/retrain' or self.path.startswith('/retrain/'):
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            # 检查是否指定了特定币种
            if self.path.startswith('/retrain/'):
                symbol = self.path.split('/')[-1]
                if symbol in self.server.analyzer.symbols:
                    # 使用更安全的方式：创建包装函数来处理单个币种训练
                    def train_single():
                        with self.server.analyzer._training_lock:
                            if not self.server.analyzer._is_training:
                                self.server.analyzer._is_training = True
                                try:
                                    logger.info(f"手动触发 {symbol} 模型重训练")
                                    self.server.analyzer._train_model(symbol)
                                    logger.info(f"{symbol} 模型重训练完成")
                                finally:
                                    self.server.analyzer._is_training = False
                            else:
                                logger.warning(f"模型正在训练中，跳过 {symbol} 训练请求")
                    
                    threading.Thread(target=train_single, daemon=True).start()
                    response = {
                        'status': 'success',
                        'message': f'Retraining {symbol} started'
                    }
                else:
                    response = {
                        'status': 'error',
                        'message': f'Symbol {symbol} not found'
                    }
            else:
                threading.Thread(target=self.server.analyzer.retrain_all).start()
                response = {
                    'status': 'success',
                    'message': 'Retraining all models started'
                }
            
            self.wfile.write(json.dumps(response).encode())
            
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass


def start_http_server(analyzer, port=8091):
    """启动HTTP服务器"""
    try:
        httpd = HTTPServer(('', port), EnhancedMLHTTPHandler)
        httpd.analyzer = analyzer
        logger.info(f"HTTP服务器启动在端口 {port}")
        httpd.serve_forever()
    except Exception as e:
        logger.error(f"HTTP服务器错误: {e}")


def main():
    """主函数"""
    import sys
    import asyncio
    from websocket_server import MLWebSocketServer
    
    # 检查命令行参数
    use_hourly = '--hourly' in sys.argv or '-h' in sys.argv
    use_websocket = '--websocket' in sys.argv or '-ws' in sys.argv
    
    print("=" * 60)
    print("🚀 增强版生产级ML策略")
    if use_hourly:
        print("📊 使用小时级数据")
    else:
        print("📊 使用日线数据")
    if use_websocket:
        print("🔌 启用WebSocket实时推送")
    print("=" * 60)
    
    # 创建分析器
    print("🔧 初始化增强版ML分析器...")
    analyzer = EnhancedProductionML(use_hourly_data=use_hourly)
    
    # 运行回测
    print("\n📊 运行修复的回测...")
    for symbol in analyzer.symbols:
        analyzer.backtest_fixed(symbol, start_date='2024-01-01')
    
    # 启动HTTP服务器
    http_thread = threading.Thread(
        target=start_http_server,
        args=(analyzer, 8091),
        daemon=True
    )
    http_thread.start()
    
    # 启动WebSocket服务器
    if use_websocket:
        ws_server = MLWebSocketServer(analyzer, port=8765)
        ws_thread = threading.Thread(
            target=lambda: asyncio.run(ws_server.start()),
            daemon=True
        )
        ws_thread.start()
        print("🔌 WebSocket服务器启动在端口 8765")
    
    print("\n✅ 增强版ML策略系统启动成功！")
    print(f"📡 HTTP API: http://localhost:8091")
    if use_websocket:
        print(f"🔌 WebSocket: ws://localhost:8765")
    print(f"📊 监控交易对: {', '.join(analyzer.symbols)}")
    print(f"🧠 已加载模型: {len(analyzer.models)} 个")
    print("\n📌 增强特性:")
    print("  - 修复的回测系统")
    print("  - 改进的标签生成策略")
    print("  - 不平衡数据处理(SMOTE)")
    print("  - 市场情绪指标集成")
    print("  - 纸上交易系统")
    if use_websocket:
        print("  - WebSocket实时信号推送")
    print("\n📌 API端点:")
    print("  GET /health   - 健康检查")
    print("  GET /signals  - 获取信号")
    print("  GET /metrics  - 查看指标和纸上交易")
    print("  GET /retrain  - 重新训练")
    if use_websocket:
        print("\n📌 WebSocket消息类型:")
        print("  welcome - 连接欢迎消息")
        print("  signals - 初始信号")
        print("  signals_update - 信号更新")
        print("  paper_trade - 纸上交易执行")
    
    # 显示初始信号
    print("\n📈 生成初始信号...")
    for symbol in analyzer.symbols:
        signal = analyzer.generate_signal(symbol)
        if signal:
            print(f"{symbol}: {signal['recommendation']} (置信度: {signal['confidence']:.2%})")
            if signal.get('paper_trade', {}).get('executed'):
                print(f"  纸上交易: {signal['paper_trade']['reason']}")
    
    # 保持运行并定期生成信号
    try:
        last_signal_time = time.time()
        signal_interval = 300  # 每5分钟生成一次信号（小时数据模式下）
        
        if use_hourly:
            signal_interval = 300  # 小时数据模式：5分钟
        else:
            signal_interval = 3600  # 日数据模式：1小时
            
        print(f"\n⏰ 将每 {signal_interval//60} 分钟生成并推送新信号")
        
        # 记录上次检查重训练的时间
        last_retrain_check = 0
        retrain_check_interval = 60  # 每分钟检查一次是否需要重训练
        
        while True:
            current_time = time.time()
            
            # 每分钟检查一次自动重训练（每天UTC 12:00）
            if current_time - last_retrain_check >= retrain_check_interval:
                analyzer.check_and_auto_retrain()
                last_retrain_check = current_time
            
            # 检查是否需要生成新信号
            if current_time - last_signal_time >= signal_interval:
                print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 生成新信号...")
                
                # 生成所有交易对的信号
                new_signals = {}
                for symbol in analyzer.symbols:
                    signal = analyzer.generate_signal(symbol)
                    if signal:
                        new_signals[symbol] = signal
                        print(f"  {symbol}: {signal['recommendation']} (置信度: {signal['confidence']:.2%})")
                
                # 如果有WebSocket客户端连接，推送信号
                if use_websocket and ws_server and new_signals:
                    # WebSocket服务器会通过定期检查自动广播变化的信号
                    # 这里只需要记录日志
                    print(f"  📤 生成了 {len(new_signals)} 个新信号")
                
                last_signal_time = current_time
            
            # 短暂休眠，避免占用过多CPU
            time.sleep(10)
            
    except KeyboardInterrupt:
        print("\n正在关闭...")


if __name__ == "__main__":
    main()