#!/usr/bin/env python3
"""
Binance API数据收集器
提供完整的OHLC数据支持，支持回测和实时分析
基于Binance免费API，无需认证即可获取历史数据
"""

import abc
import sys
import json
import time
import datetime
from abc import ABC
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import asyncio

import fire
import pandas as pd
import numpy as np
from loguru import logger
from dateutil.tz import tzlocal
import requests

CUR_DIR = Path(__file__).resolve().parent
sys.path.append(str(CUR_DIR.parent.parent))
from data_collector.base import BaseCollector, BaseNormalize, BaseRun
from data_collector.utils import deco_retry


class BinanceCryptoCollector(BaseCollector):
    """Binance加密货币数据收集器，提供完整OHLC数据支持"""
    
    # Binance API端点
    BASE_URL = "https://api.binance.com"
    KLINES_ENDPOINT = "/api/v3/klines"
    EXCHANGE_INFO_ENDPOINT = "/api/v3/exchangeInfo"
    
    # 支持的时间间隔映射
    INTERVAL_MAPPING = {
        "1m": "1m",
        "5m": "5m", 
        "15m": "15m",
        "1h": "1h",
        "4h": "4h",
        "1d": "1d",
        "1w": "1w",
    }
    
    def __init__(
        self,
        save_dir: [str, Path],
        start=None,
        end=None,
        interval="1d",
        max_workers=1,
        max_collector_count=2,
        delay=0.1,  # Binance限制较宽松，可以更快
        check_data_length: int = None,
        limit_nums: int = None,
        api_key: str = None,
        api_secret: str = None,
    ):
        """
        初始化Binance数据收集器
        
        Parameters
        ----------
        save_dir: str
            数据保存目录
        start: str
            开始日期
        end: str  
            结束日期
        interval: str
            时间间隔，支持 [1m, 5m, 15m, 1h, 4h, 1d, 1w]
        max_workers: int
            并发数，默认1
        max_collector_count: int
            最大收集次数，默认2
        delay: float
            请求延迟（秒），默认0.1
        check_data_length: int
            检查数据长度
        limit_nums: int
            限制符号数量（用于调试）
        api_key: str
            Binance API密钥（可选，历史数据无需认证）
        api_secret: str
            Binance API密钥（可选，历史数据无需认证）
        """
        super(BinanceCryptoCollector, self).__init__(
            save_dir=save_dir,
            start=start,
            end=end,
            interval=interval,
            max_workers=max_workers,
            max_collector_count=max_collector_count,
            delay=delay,
            check_data_length=check_data_length,
            limit_nums=limit_nums,
        )
        
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = requests.Session()
        
        # 设置请求头
        if api_key:
            self.session.headers.update({'X-MBX-APIKEY': api_key})
        
        self.init_datetime()
        self._validate_interval()

    def _validate_interval(self):
        """验证时间间隔是否支持"""
        if self.interval not in self.INTERVAL_MAPPING:
            raise ValueError(f"不支持的时间间隔: {self.interval}，支持的间隔: {list(self.INTERVAL_MAPPING.keys())}")

    def init_datetime(self):
        """初始化时间范围"""
        if self.interval == self.INTERVAL_1min:
            self.start_datetime = max(self.start_datetime, self.DEFAULT_START_DATETIME_1MIN)
        elif self.interval == self.INTERVAL_1d:
            pass
        else:
            # 其他间隔的默认开始时间
            pass
            
        self.start_datetime = self.convert_datetime(self.start_datetime, self._timezone)
        self.end_datetime = self.convert_datetime(self.end_datetime, self._timezone)

    @staticmethod
    def convert_datetime(dt: [pd.Timestamp, datetime.date, str], timezone):
        """转换时间格式"""
        try:
            dt = pd.Timestamp(dt, tz=timezone).timestamp()
            dt = pd.Timestamp(dt, tz=tzlocal(), unit="s")
        except ValueError:
            pass
        return dt

    @property
    @abc.abstractmethod
    def _timezone(self):
        raise NotImplementedError("子类需要实现时区设置")

    @deco_retry
    def get_exchange_info(self) -> Dict:
        """获取交易所信息，包括所有交易对"""
        try:
            url = f"{self.BASE_URL}{self.EXCHANGE_INFO_ENDPOINT}"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"获取交易所信息失败: {e}")
            raise

    @deco_retry  
    def get_crypto_symbols(self) -> List[str]:
        """获取所有可用的加密货币交易对"""
        try:
            exchange_info = self.get_exchange_info()
            
            # 过滤USDT交易对和状态为TRADING的
            symbols = []
            for symbol_info in exchange_info.get('symbols', []):
                symbol = symbol_info['symbol']
                status = symbol_info['status']
                quote_asset = symbol_info['quoteAsset']
                
                # 只获取USDT交易对且状态为TRADING的
                if status == 'TRADING' and quote_asset == 'USDT':
                    symbols.append(symbol)
            
            logger.info(f"从Binance获取到 {len(symbols)} 个USDT交易对")
            return sorted(symbols)
            
        except Exception as e:
            logger.error(f"获取交易对列表失败: {e}")
            return []

    @deco_retry
    def get_klines_data(self, symbol: str, interval: str, start_time: int, end_time: int, limit: int = 1000) -> List:
        """获取K线数据"""
        try:
            url = f"{self.BASE_URL}{self.KLINES_ENDPOINT}"
            
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': limit,
            }
            
            if start_time:
                params['startTime'] = start_time
            if end_time:
                params['endTime'] = end_time
            
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.debug(f"获取 {symbol} 数据: {len(data)} 条记录")
            return data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"获取 {symbol} K线数据失败: {e}")
            raise
        except Exception as e:
            logger.error(f"处理 {symbol} 数据时出错: {e}")
            raise

    def convert_klines_to_dataframe(self, klines_data: List, symbol: str) -> pd.DataFrame:
        """将K线数据转换为DataFrame"""
        if not klines_data:
            return pd.DataFrame()
        
        try:
            # Binance K线数据格式:
            # [
            #   [timestamp, open, high, low, close, volume, close_time, 
            #    quote_volume, count, taker_buy_volume, taker_buy_quote_volume, ignore]
            # ]
            
            df = pd.DataFrame(klines_data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'count', 'taker_buy_volume', 
                'taker_buy_quote_volume', 'ignore'
            ])
            
            # 转换数据类型
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df['date'] = df['timestamp'].dt.date
            df['symbol'] = symbol
            
            # 转换数值列
            numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'quote_volume']
            for col in numeric_columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 选择需要的列
            result_df = df[['date', 'symbol', 'open', 'high', 'low', 'close', 'volume', 'quote_volume']].copy()
            
            # 去重并排序
            result_df = result_df.drop_duplicates(subset=['date', 'symbol']).sort_values('date')
            result_df = result_df.reset_index(drop=True)
            
            return result_df
            
        except Exception as e:
            logger.error(f"转换K线数据失败: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_data_from_remote(symbol: str, interval: str, start: str, end: str) -> Optional[pd.DataFrame]:
        """从Binance API获取数据"""
        collector = BinanceCryptoCollector(
            save_dir="/tmp",  # 临时目录
            start=start,
            end=end,
            interval=interval
        )
        collector._timezone = "UTC"  # 设置时区
        
        try:
            # 转换时间格式
            start_timestamp = int(pd.Timestamp(start).timestamp() * 1000)
            end_timestamp = int(pd.Timestamp(end).timestamp() * 1000)
            
            # 获取Binance间隔格式
            binance_interval = collector.INTERVAL_MAPPING.get(interval, "1d")
            
            # 分批获取数据（Binance单次最多1000条）
            all_data = []
            current_start = start_timestamp
            
            while current_start < end_timestamp:
                # 计算当前批次的结束时间
                if interval == "1d":
                    # 日线数据：1000天
                    batch_end = min(current_start + 1000 * 24 * 60 * 60 * 1000, end_timestamp)
                elif interval == "1h":
                    # 小时数据：1000小时
                    batch_end = min(current_start + 1000 * 60 * 60 * 1000, end_timestamp)
                elif interval == "1m":
                    # 分钟数据：1000分钟
                    batch_end = min(current_start + 1000 * 60 * 1000, end_timestamp)
                else:
                    # 其他间隔的处理
                    batch_end = end_timestamp
                
                # 获取批次数据
                batch_data = collector.get_klines_data(
                    symbol=symbol,
                    interval=binance_interval,
                    start_time=current_start,
                    end_time=batch_end,
                    limit=1000
                )
                
                if not batch_data:
                    break
                
                all_data.extend(batch_data)
                
                # 更新下次开始时间
                if len(batch_data) < 1000:
                    # 如果返回数据少于1000条，说明已经获取完毕
                    break
                
                # 使用最后一条数据的时间戳作为下次开始时间
                current_start = batch_data[-1][0] + 1
                
                # 避免请求过快
                time.sleep(collector.delay)
            
            if not all_data:
                logger.warning(f"未获取到 {symbol} 的数据")
                return pd.DataFrame()
            
            # 转换为DataFrame
            df = collector.convert_klines_to_dataframe(all_data, symbol)
            
            # 过滤日期范围
            if not df.empty:
                start_date = pd.to_datetime(start).date()
                end_date = pd.to_datetime(end).date()
                df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]
            
            logger.info(f"获取 {symbol} 数据完成: {len(df)} 条记录")
            return df
            
        except Exception as e:
            logger.error(f"获取 {symbol} 远程数据失败: {e}")
            return pd.DataFrame()

    def get_data(
        self, symbol: str, interval: str, start_datetime: pd.Timestamp, end_datetime: pd.Timestamp
    ) -> Optional[pd.DataFrame]:
        """获取指定符号的数据"""
        def _get_simple(start_, end_):
            self.sleep()
            return self.get_data_from_remote(
                symbol,
                interval=interval,
                start=start_,
                end=end_,
            )

        if interval in self.INTERVAL_MAPPING:
            _result = _get_simple(start_datetime, end_datetime)
        else:
            raise ValueError(f"不支持的时间间隔: {interval}")
        return _result


class BinanceCryptoCollector1d(BinanceCryptoCollector, ABC):
    """Binance日线数据收集器"""
    
    def get_instrument_list(self):
        """获取交易对列表"""
        logger.info("获取Binance交易对列表...")
        symbols = self.get_crypto_symbols()
        logger.info(f"获取到 {len(symbols)} 个交易对")
        return symbols

    def normalize_symbol(self, symbol):
        """标准化符号格式"""
        return symbol.upper()

    @property
    def _timezone(self):
        return "UTC"


class BinanceCryptoCollector1h(BinanceCryptoCollector, ABC):
    """Binance小时线数据收集器"""
    
    def get_instrument_list(self):
        logger.info("获取Binance交易对列表（1h）...")
        symbols = self.get_crypto_symbols()
        logger.info(f"获取到 {len(symbols)} 个交易对")
        return symbols

    def normalize_symbol(self, symbol):
        return symbol.upper()

    @property
    def _timezone(self):
        return "UTC"


class BinanceCryptoCollector1m(BinanceCryptoCollector, ABC):
    """Binance分钟线数据收集器"""
    
    def get_instrument_list(self):
        logger.info("获取Binance交易对列表（1m）...")
        symbols = self.get_crypto_symbols()
        # 分钟数据量大，可以限制符号数量
        if len(symbols) > 50:
            symbols = symbols[:50]
            logger.info(f"分钟数据限制为前 {len(symbols)} 个交易对")
        return symbols

    def normalize_symbol(self, symbol):
        return symbol.upper()

    @property
    def _timezone(self):
        return "UTC"


class BinanceCryptoNormalize(BaseNormalize):
    """Binance数据标准化处理器"""
    
    DAILY_FORMAT = "%Y-%m-%d"
    HOURLY_FORMAT = "%Y-%m-%d %H:%M:%S"

    @staticmethod
    def normalize_binance_ohlc(
        df: pd.DataFrame,
        calendar_list: list = None,
        date_field_name: str = "date",
        symbol_field_name: str = "symbol",
    ):
        """标准化Binance OHLC数据"""
        if df.empty:
            return df
            
        df = df.copy()
        df.set_index(date_field_name, inplace=True)
        df.index = pd.to_datetime(df.index)
        
        # 去重，保留第一个
        df = df[~df.index.duplicated(keep="first")]
        
        # 确保OHLC列存在且为数值类型
        required_columns = ['open', 'high', 'low', 'close', 'volume']
        for col in required_columns:
            if col not in df.columns:
                df[col] = 0.0
            else:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
        
        # 数据验证：确保 high >= max(open, close) 且 low <= min(open, close)
        df.loc[df['high'] < df[['open', 'close']].max(axis=1), 'high'] = df[['open', 'close']].max(axis=1)
        df.loc[df['low'] > df[['open', 'close']].min(axis=1), 'low'] = df[['open', 'close']].min(axis=1)
        
        # 如果提供了日历，则重索引
        if calendar_list is not None:
            df = df.reindex(
                pd.DataFrame(index=calendar_list)
                .loc[
                    pd.Timestamp(df.index.min()).date() : pd.Timestamp(df.index.max()).date()
                    + pd.Timedelta(hours=23, minutes=59)
                ]
                .index
            )
            
        df.sort_index(inplace=True)
        df.index.names = [date_field_name]
        return df.reset_index()

    def normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        """标准化数据"""
        df = self.normalize_binance_ohlc(df, self._calendar_list, self._date_field_name, self._symbol_field_name)
        return df


class BinanceCryptoNormalize1d(BinanceCryptoNormalize):
    """日线数据标准化"""
    def _get_calendar_list(self):
        return None


class BinanceCryptoNormalize1h(BinanceCryptoNormalize):
    """小时数据标准化"""
    def _get_calendar_list(self):
        return None


class BinanceCryptoNormalize1m(BinanceCryptoNormalize):
    """分钟数据标准化"""
    def _get_calendar_list(self):
        return None


class BinanceRun(BaseRun):
    """Binance数据收集运行器"""
    
    def __init__(self, source_dir=None, normalize_dir=None, max_workers=1, interval="1d"):
        """
        初始化运行器
        
        Parameters
        ----------
        source_dir: str
            原始数据保存目录，默认 "当前目录/binance_source"
        normalize_dir: str
            标准化数据保存目录，默认 "当前目录/binance_normalize"  
        max_workers: int
            并发数，默认1
        interval: str
            时间间隔，支持 [1m, 5m, 15m, 1h, 4h, 1d, 1w]，默认1d
        """
        super().__init__(source_dir, normalize_dir, max_workers, interval)

    @property
    def collector_class_name(self):
        return f"BinanceCryptoCollector{self.interval}"

    @property
    def normalize_class_name(self):
        return f"BinanceCryptoNormalize{self.interval}"

    @property
    def default_base_dir(self) -> [Path, str]:
        return CUR_DIR / "binance_data"

    def download_data(
        self,
        max_collector_count=2,
        delay=0.1,
        start=None,
        end=None,
        check_data_length: int = None,
        limit_nums=None,
        api_key: str = None,
        api_secret: str = None,
    ):
        """
        下载Binance数据
        
        Parameters
        ----------
        max_collector_count: int
            最大收集次数，默认2
        delay: float
            请求延迟（秒），默认0.1
        start: str
            开始日期，格式："2023-01-01"
        end: str
            结束日期，格式："2024-12-31"
        check_data_length: int
            检查数据长度阈值
        limit_nums: int
            限制符号数量（调试用）
        api_key: str
            Binance API密钥（可选，历史数据无需认证）
        api_secret: str
            Binance API密钥（可选，历史数据无需认证）
            
        Examples
        --------
        # 下载日线数据
        python binance_collector.py download_data --source_dir ~/.qlib/binance_data/source/1d --start 2023-01-01 --end 2024-12-31 --interval 1d
        
        # 下载小时数据
        python binance_collector.py download_data --source_dir ~/.qlib/binance_data/source/1h --start 2024-01-01 --end 2024-12-31 --interval 1h --limit_nums 10
        
        # 下载分钟数据（建议限制符号数量）
        python binance_collector.py download_data --source_dir ~/.qlib/binance_data/source/1m --start 2024-12-01 --end 2024-12-31 --interval 1m --limit_nums 5
        """
        
        # 存储API凭证（如果提供）
        if api_key:
            import os
            os.environ['BINANCE_API_KEY'] = api_key
        if api_secret:
            os.environ['BINANCE_API_SECRET'] = api_secret
            
        super(BinanceRun, self).download_data(
            max_collector_count, delay, start, end, check_data_length, limit_nums
        )

    def normalize_data(self, date_field_name: str = "date", symbol_field_name: str = "symbol"):
        """
        标准化OHLC数据
        
        Parameters
        ----------
        date_field_name: str
            日期字段名，默认"date"
        symbol_field_name: str
            符号字段名，默认"symbol"
            
        Examples
        --------
        # 标准化日线数据
        python binance_collector.py normalize_data --source_dir ~/.qlib/binance_data/source/1d --normalize_dir ~/.qlib/binance_data/normalize/1d --interval 1d
        
        # 标准化小时数据
        python binance_collector.py normalize_data --source_dir ~/.qlib/binance_data/source/1h --normalize_dir ~/.qlib/binance_data/normalize/1h --interval 1h
        """
        super(BinanceRun, self).normalize_data(date_field_name, symbol_field_name)

    def get_realtime_data(self, symbols: List[str] = None, interval: str = "1d") -> Dict:
        """
        获取实时数据（用于实时分析）
        
        Parameters
        ----------
        symbols: List[str]
            交易对列表，如 ["BTCUSDT", "ETHUSDT"]
        interval: str
            时间间隔
            
        Returns
        -------
        Dict
            实时数据字典
        """
        if symbols is None:
            collector = BinanceCryptoCollector1d(save_dir="/tmp", interval=interval)
            symbols = collector.get_crypto_symbols()[:20]  # 获取前20个交易对
        
        realtime_data = {}
        
        for symbol in symbols:
            try:
                # 获取最近的数据
                end_date = datetime.datetime.now().strftime("%Y-%m-%d")
                start_date = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
                
                df = self.get_data_from_remote(symbol, interval, start_date, end_date)
                
                if df is not None and not df.empty:
                    latest = df.iloc[-1]
                    realtime_data[symbol] = {
                        'symbol': symbol,
                        'date': str(latest['date']),
                        'open': float(latest['open']),
                        'high': float(latest['high']),
                        'low': float(latest['low']),
                        'close': float(latest['close']),
                        'volume': float(latest['volume']),
                    }
                    
            except Exception as e:
                logger.error(f"获取 {symbol} 实时数据失败: {e}")
                
        return realtime_data


if __name__ == "__main__":
    fire.Fire(BinanceRun)