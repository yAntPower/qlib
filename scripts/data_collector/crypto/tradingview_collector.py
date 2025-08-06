import abc
import sys
import datetime
import json
from abc import ABC
from pathlib import Path
from typing import Optional, Dict, List
import time

import fire
import pandas as pd
from loguru import logger
from dateutil.tz import tzlocal

CUR_DIR = Path(__file__).resolve().parent
sys.path.append(str(CUR_DIR.parent.parent))
from data_collector.base import BaseCollector, BaseNormalize, BaseRun
from data_collector.utils import deco_retry

try:
    from tradingview_screener import Query
    from http.cookiejar import CookieJar
    import requests
    TRADINGVIEW_AVAILABLE = True
except ImportError:
    TRADINGVIEW_AVAILABLE = False
    logger.warning("tradingview-screener not installed. Please install with: pip install tradingview-screener")


class TradingViewCryptoCollector(BaseCollector):
    """TradingView crypto data collector with OHLC support for backtesting"""
    
    # Supported intervals mapping to TradingView timeframes
    INTERVAL_MAPPING = {
        "1d": "1D",
        "1h": "1H", 
        "4h": "4H",
        "15m": "15",
        "5m": "5",
        "1m": "1"
    }
    
    def __init__(
        self,
        save_dir: [str, Path],
        start=None,
        end=None,
        interval="1d",
        max_workers=1,
        max_collector_count=2,
        delay=1,
        check_data_length: int = None,
        limit_nums: int = None,
        tv_username: str = None,
        tv_password: str = None,
    ):
        """
        TradingView crypto data collector
        
        Parameters
        ----------
        save_dir: str
            crypto save dir
        start: str
            start datetime
        end: str  
            end datetime
        interval: str
            freq, value from [1m, 5m, 15m, 1h, 4h, 1d], default 1d
        tv_username: str
            TradingView username for premium features
        tv_password: str
            TradingView password for premium features
        """
        if not TRADINGVIEW_AVAILABLE:
            raise ImportError("tradingview-screener package is required. Install with: pip install tradingview-screener")
            
        super(TradingViewCryptoCollector, self).__init__(
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
        
        self.tv_username = tv_username
        self.tv_password = tv_password
        self.cookies = None
        
        if tv_username and tv_password:
            self.cookies = self._authenticate()
        
        self.init_datetime()

    def _authenticate(self) -> Optional[CookieJar]:
        """Authenticate with TradingView"""
        try:
            session = requests.Session()
            r = session.post(
                'https://www.tradingview.com/accounts/signin/',
                headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.tradingview.com'},
                data={'username': self.tv_username, 'password': self.tv_password, 'remember': 'on'},
                timeout=60,
            )
            r.raise_for_status()
            if r.json().get('error'):
                logger.error(f'Failed to authenticate: {r.json()}')
                return None
            logger.info("Successfully authenticated with TradingView")
            return session.cookies
        except Exception as e:
            logger.warning(f"TradingView authentication failed: {e}")
            return None

    def init_datetime(self):
        """Initialize datetime based on interval"""
        if self.interval == self.INTERVAL_1min:
            self.start_datetime = max(self.start_datetime, self.DEFAULT_START_DATETIME_1MIN)
        elif self.interval == self.INTERVAL_1d:
            pass
        else:
            # Support for other intervals like 1h, 4h, 15m, 5m
            pass
            
        self.start_datetime = self.convert_datetime(self.start_datetime, self._timezone)
        self.end_datetime = self.convert_datetime(self.end_datetime, self._timezone)

    @staticmethod
    def convert_datetime(dt: [pd.Timestamp, datetime.date, str], timezone):
        """Convert datetime to proper timezone"""
        try:
            dt = pd.Timestamp(dt, tz=timezone).timestamp()
            dt = pd.Timestamp(dt, tz=tzlocal(), unit="s")
        except ValueError:
            pass
        return dt

    @property
    @abc.abstractmethod
    def _timezone(self):
        raise NotImplementedError("rewrite get_timezone")

    @deco_retry
    def get_crypto_symbols(self) -> List[str]:
        """Get crypto symbols from TradingView"""
        try:
            query = Query().select(
                'name', 'close', 'volume', 'market_cap_basic'
            ).where(
                'market', 'in', ['crypto']
            ).order_by('market_cap_basic', False)
            
            data = query.get_scanner_data(cookies=self.cookies)
            symbols = [row['name'] for row in data[1]]
            logger.info(f"Retrieved {len(symbols)} crypto symbols from TradingView")
            return symbols
        except Exception as e:
            logger.error(f"Failed to get crypto symbols: {e}")
            return []

    @deco_retry
    def get_ohlc_data(self, symbol: str, interval: str, start: str, end: str) -> Optional[pd.DataFrame]:
        """Get OHLC data for a crypto symbol"""
        try:
            # Map interval to TradingView format
            tv_interval = self.INTERVAL_MAPPING.get(interval, "1D")
            
            # Query OHLC data with volume
            query = Query().select(
                f'open|{tv_interval}',
                f'high|{tv_interval}', 
                f'low|{tv_interval}',
                f'close|{tv_interval}',
                f'volume|{tv_interval}',
                'name'
            ).where(
                'name', 'match', symbol
            )
            
            data = query.get_scanner_data(cookies=self.cookies)
            
            if not data[1]:
                logger.warning(f"No data found for {symbol}")
                return None
                
            # Convert to DataFrame with OHLC format
            df_data = []
            for row in data[1]:
                df_data.append({
                    'symbol': symbol,
                    'open': row.get(f'open|{tv_interval}', 0),
                    'high': row.get(f'high|{tv_interval}', 0), 
                    'low': row.get(f'low|{tv_interval}', 0),
                    'close': row.get(f'close|{tv_interval}', 0),
                    'volume': row.get(f'volume|{tv_interval}', 0),
                    'date': pd.Timestamp.now().strftime('%Y-%m-%d')  # Simplified for now
                })
            
            df = pd.DataFrame(df_data)
            return df
            
        except Exception as e:
            logger.error(f"Failed to get OHLC data for {symbol}: {e}")
            return None

    @staticmethod
    def get_data_from_remote(symbol, interval, start, end):
        """Get data from TradingView remote API"""
        # This method will be implemented by subclasses
        raise NotImplementedError("Subclass should implement this method")

    def get_data(
        self, symbol: str, interval: str, start_datetime: pd.Timestamp, end_datetime: pd.Timestamp
    ) -> Optional[pd.DataFrame]:
        """Get data for a symbol"""
        def _get_simple(start_, end_):
            self.sleep()
            return self.get_ohlc_data(
                symbol,
                interval=interval,
                start=start_,
                end=end_,
            )

        if interval in self.INTERVAL_MAPPING:
            _result = _get_simple(start_datetime, end_datetime)
        else:
            raise ValueError(f"Unsupported interval: {interval}")
        return _result


class TradingViewCryptoCollector1d(TradingViewCryptoCollector, ABC):
    """Daily crypto data collector"""
    
    def get_instrument_list(self):
        """Get list of crypto instruments"""
        logger.info("Getting TradingView crypto symbols...")
        symbols = self.get_crypto_symbols()
        logger.info(f"Retrieved {len(symbols)} symbols.")
        return symbols

    def normalize_symbol(self, symbol):
        """Normalize symbol format"""
        # Convert TradingView symbol format to standard format
        # Example: BINANCE:BTCUSDT -> BTCUSDT
        if ':' in symbol:
            return symbol.split(':')[-1]
        return symbol

    @property
    def _timezone(self):
        return "UTC"

    @staticmethod
    def get_data_from_remote(symbol, interval, start, end):
        """Get data from TradingView for daily interval"""
        # This is a placeholder - actual implementation would use TradingView API
        logger.info(f"Fetching {symbol} data from {start} to {end}")
        return None


class TradingViewCryptoCollector1h(TradingViewCryptoCollector, ABC):
    """Hourly crypto data collector"""
    
    def get_instrument_list(self):
        logger.info("Getting TradingView crypto symbols for 1h data...")
        symbols = self.get_crypto_symbols()
        logger.info(f"Retrieved {len(symbols)} symbols.")
        return symbols

    def normalize_symbol(self, symbol):
        if ':' in symbol:
            return symbol.split(':')[-1]
        return symbol

    @property
    def _timezone(self):
        return "UTC"

    @staticmethod
    def get_data_from_remote(symbol, interval, start, end):
        logger.info(f"Fetching {symbol} hourly data from {start} to {end}")
        return None


class TradingViewCryptoNormalize(BaseNormalize):
    """TradingView crypto data normalizer with OHLC support"""
    
    DAILY_FORMAT = "%Y-%m-%d"
    HOURLY_FORMAT = "%Y-%m-%d %H:%M:%S"

    @staticmethod
    def normalize_crypto_ohlc(
        df: pd.DataFrame,
        calendar_list: list = None,
        date_field_name: str = "date",
        symbol_field_name: str = "symbol",
    ):
        """Normalize crypto OHLC data"""
        if df.empty:
            return df
            
        df = df.copy()
        df.set_index(date_field_name, inplace=True)
        df.index = pd.to_datetime(df.index)
        df = df[~df.index.duplicated(keep="first")]
        
        # Ensure OHLC columns exist
        required_columns = ['open', 'high', 'low', 'close', 'volume']
        for col in required_columns:
            if col not in df.columns:
                df[col] = 0.0
                
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
        """Normalize data"""
        df = self.normalize_crypto_ohlc(df, self._calendar_list, self._date_field_name, self._symbol_field_name)
        return df


class TradingViewCryptoNormalize1d(TradingViewCryptoNormalize):
    """Daily normalizer"""
    def _get_calendar_list(self):
        return None


class TradingViewCryptoNormalize1h(TradingViewCryptoNormalize):
    """Hourly normalizer"""
    def _get_calendar_list(self):
        return None


class TradingViewRun(BaseRun):
    """TradingView crypto data collection runner"""
    
    def __init__(self, source_dir=None, normalize_dir=None, max_workers=1, interval="1d"):
        """
        TradingView crypto data collection runner
        
        Parameters
        ----------
        source_dir: str
            The directory where the raw data collected from TradingView is saved
        normalize_dir: str
            Directory for normalize data
        max_workers: int
            Concurrent number, default is 1
        interval: str
            freq, value from [1m, 5m, 15m, 1h, 4h, 1d], default 1d
        """
        super().__init__(source_dir, normalize_dir, max_workers, interval)

    @property
    def collector_class_name(self):
        return f"TradingViewCryptoCollector{self.interval}"

    @property
    def normalize_class_name(self):
        return f"TradingViewCryptoNormalize{self.interval}"

    @property
    def default_base_dir(self) -> [Path, str]:
        return CUR_DIR

    def download_data(
        self,
        max_collector_count=2,
        delay=1,
        start=None,
        end=None,
        check_data_length: int = None,
        limit_nums=None,
        tv_username: str = None,
        tv_password: str = None,
    ):
        """Download OHLC data from TradingView
        
        Parameters
        ----------
        tv_username: str
            TradingView username for premium features
        tv_password: str
            TradingView password for premium features
            
        Examples
        --------
        # Download daily OHLC data
        $ python tradingview_collector.py download_data --source_dir ~/.qlib/crypto_tv_data/source/1d --start 2023-01-01 --end 2024-12-31 --interval 1d --tv_username your_username --tv_password your_password
        
        # Download hourly data
        $ python tradingview_collector.py download_data --source_dir ~/.qlib/crypto_tv_data/source/1h --start 2024-01-01 --end 2024-12-31 --interval 1h
        """
        
        # Store credentials for collector
        if tv_username and tv_password:
            import os
            os.environ['TV_USERNAME'] = tv_username
            os.environ['TV_PASSWORD'] = tv_password
            
        super(TradingViewRun, self).download_data(
            max_collector_count, delay, start, end, check_data_length, limit_nums
        )

    def normalize_data(self, date_field_name: str = "date", symbol_field_name: str = "symbol"):
        """Normalize OHLC data
        
        Examples
        --------
        $ python tradingview_collector.py normalize_data --source_dir ~/.qlib/crypto_tv_data/source/1d --normalize_dir ~/.qlib/crypto_tv_data/source/1d_nor --interval 1d --date_field_name date
        """
        super(TradingViewRun, self).normalize_data(date_field_name, symbol_field_name)


if __name__ == "__main__":
    fire.Fire(TradingViewRun)