#!/usr/bin/env python3
"""
Binance数据转换脚本
将Binance CSV格式数据转换为qlib二进制格式
支持完整的OHLC数据，可用于策略回测
"""

import abc
import sys
import datetime
from pathlib import Path

import fire
import pandas as pd
from loguru import logger

CUR_DIR = Path(__file__).resolve().parent
sys.path.append(str(CUR_DIR.parent.parent))
from dump_bin import DumpDataBase
from qlib.utils import code_to_fname, fname_to_code


class DumpBinance(DumpDataBase):
    """Binance数据转换器"""

    SYMBOL_FIELD_NAME = "symbol"
    DATE_FIELD_NAME = "date"
    
    # Binance OHLC字段映射
    OHLC_FIELDS = ["open", "high", "low", "close", "volume", "quote_volume"]
    
    def __init__(
        self,
        csv_path: str,
        qlib_dir: str,
        backup_dir: str = None,
        freq: str = "day",
        max_workers: int = 16,
        date_field_name: str = "date",
        file_suffix: str = ".csv",
        symbol_field_name: str = "symbol",
        exclude_fields: str = "",
        include_fields: str = "",
        limit_nums: int = None,
    ):
        """
        初始化Binance数据转换器
        
        Parameters
        ----------
        csv_path: str
            CSV数据目录路径
        qlib_dir: str
            qlib数据输出目录
        backup_dir: str
            备份目录（可选）
        freq: str
            数据频率，"day"或"1min"
        max_workers: int
            并发数，默认16
        date_field_name: str
            日期字段名，默认"date"
        file_suffix: str
            文件后缀，默认".csv"
        symbol_field_name: str
            符号字段名，默认"symbol"
        exclude_fields: str
            排除字段，逗号分隔
        include_fields: str
            包含字段，逗号分隔，默认包含所有OHLC字段
        limit_nums: int
            限制处理的文件数量（调试用）
        """
        
        # 设置默认包含字段
        if not include_fields:
            include_fields = ",".join(self.OHLC_FIELDS)
        
        super().__init__(
            csv_path=csv_path,
            qlib_dir=qlib_dir,
            backup_dir=backup_dir,
            freq=freq,
            max_workers=max_workers,
            date_field_name=date_field_name,
            file_suffix=file_suffix,
            symbol_field_name=symbol_field_name,
            exclude_fields=exclude_fields,
            include_fields=include_fields,
            limit_nums=limit_nums,
        )

    def _get_source_data(self, file_path: Path) -> pd.DataFrame:
        """读取并处理Binance CSV数据"""
        try:
            df = pd.read_csv(file_path)
            logger.info(f"读取文件 {file_path}: {len(df)} 条记录")
            
            if df.empty:
                logger.warning(f"文件 {file_path} 为空")
                return df
            
            # 检查必需字段
            required_fields = [self.DATE_FIELD_NAME, self.SYMBOL_FIELD_NAME]
            missing_fields = [field for field in required_fields if field not in df.columns]
            if missing_fields:
                logger.error(f"文件 {file_path} 缺少必需字段: {missing_fields}")
                return pd.DataFrame()
            
            # 转换日期格式
            df[self.DATE_FIELD_NAME] = pd.to_datetime(df[self.DATE_FIELD_NAME]).dt.date
            
            # 验证和清理OHLC数据
            df = self._validate_ohlc_data(df, file_path)
            
            # 按日期排序
            df = df.sort_values(self.DATE_FIELD_NAME).reset_index(drop=True)
            
            logger.info(f"处理完成 {file_path}: {len(df)} 条有效记录")
            return df
            
        except Exception as e:
            logger.error(f"读取文件 {file_path} 失败: {e}")
            return pd.DataFrame()

    def _validate_ohlc_data(self, df: pd.DataFrame, file_path: Path) -> pd.DataFrame:
        """验证和清理OHLC数据"""
        try:
            # 转换数值列
            numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'quote_volume']
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 删除包含NaN的行
            before_count = len(df)
            df = df.dropna(subset=[col for col in numeric_columns if col in df.columns])
            after_count = len(df)
            
            if before_count > after_count:
                logger.warning(f"文件 {file_path}: 删除了 {before_count - after_count} 行无效数据")
            
            # 验证OHLC逻辑：High >= max(Open, Close), Low <= min(Open, Close)
            if all(col in df.columns for col in ['open', 'high', 'low', 'close']):
                # 修正不合理的数据
                invalid_high = df['high'] < df[['open', 'close']].max(axis=1)
                invalid_low = df['low'] > df[['open', 'close']].min(axis=1)
                
                if invalid_high.sum() > 0:
                    logger.warning(f"文件 {file_path}: 修正了 {invalid_high.sum()} 行高价数据")
                    df.loc[invalid_high, 'high'] = df.loc[invalid_high, ['open', 'close']].max(axis=1)
                
                if invalid_low.sum() > 0:
                    logger.warning(f"文件 {file_path}: 修正了 {invalid_low.sum()} 行低价数据")
                    df.loc[invalid_low, 'low'] = df.loc[invalid_low, ['open', 'close']].min(axis=1)
            
            # 删除价格为0的行
            if 'close' in df.columns:
                zero_price = df['close'] <= 0
                if zero_price.sum() > 0:
                    logger.warning(f"文件 {file_path}: 删除了 {zero_price.sum()} 行零价格数据")
                    df = df[~zero_price]
            
            return df
            
        except Exception as e:
            logger.error(f"验证OHLC数据失败 {file_path}: {e}")
            return df

    def get_symbol_from_file(self, file_path: Path) -> str:
        """从文件路径或文件内容获取交易对符号"""
        try:
            # 首先尝试从文件名获取
            file_name = file_path.stem  # 去掉扩展名
            
            # 如果文件名是交易对格式（如BTCUSDT.csv）
            if file_name.endswith('USDT') or file_name.endswith('BTC') or file_name.endswith('ETH'):
                return file_name.upper()
            
            # 否则从文件内容读取第一行的symbol字段
            df = pd.read_csv(file_path, nrows=1)
            if self.SYMBOL_FIELD_NAME in df.columns and not df.empty:
                return df[self.SYMBOL_FIELD_NAME].iloc[0]
            
            # 如果都没有，使用文件名
            return file_name.upper()
            
        except Exception as e:
            logger.error(f"无法从文件 {file_path} 获取交易对: {e}")
            return file_path.stem.upper()

    def _dump_bin(self, df: pd.DataFrame, file_path: Path, symbol: str):
        """将数据转换为qlib二进制格式"""
        if df.empty:
            logger.warning(f"跳过空数据文件: {file_path}")
            return
        
        try:
            # 设置符号
            df = df.copy()
            df[self.SYMBOL_FIELD_NAME] = symbol
            
            # 调用父类方法进行转换
            super()._dump_bin(df, file_path)
            logger.info(f"成功转换 {symbol}: {len(df)} 条记录")
            
        except Exception as e:
            logger.error(f"转换 {symbol} 数据失败: {e}")

    def dump_all(self):
        """转换所有数据文件"""
        logger.info(f"开始转换Binance数据: {self.csv_path} -> {self.qlib_dir}")
        logger.info(f"包含字段: {self.include_fields}")
        logger.info(f"排除字段: {self.exclude_fields}")
        
        csv_path = Path(self.csv_path)
        if not csv_path.exists():
            logger.error(f"CSV路径不存在: {csv_path}")
            return
        
        # 获取所有CSV文件
        csv_files = list(csv_path.glob(f"*{self.file_suffix}"))
        if not csv_files:
            logger.error(f"未找到CSV文件: {csv_path}/*{self.file_suffix}")
            return
        
        logger.info(f"找到 {len(csv_files)} 个CSV文件")
        
        # 限制处理数量（调试用）
        if self.limit_nums and self.limit_nums > 0:
            csv_files = csv_files[:self.limit_nums]
            logger.info(f"限制处理文件数量: {len(csv_files)}")
        
        successful_count = 0
        failed_count = 0
        
        for file_path in csv_files:
            try:
                # 获取交易对符号
                symbol = self.get_symbol_from_file(file_path)
                
                # 读取和处理数据
                df = self._get_source_data(file_path)
                
                if not df.empty:
                    # 转换为二进制格式
                    self._dump_bin(df, file_path, symbol)
                    successful_count += 1
                else:
                    logger.warning(f"跳过空文件: {file_path}")
                    failed_count += 1
                    
            except Exception as e:
                logger.error(f"处理文件 {file_path} 失败: {e}")
                failed_count += 1
        
        logger.info(f"转换完成: 成功 {successful_count} 个，失败 {failed_count} 个")
        logger.info(f"qlib数据保存在: {self.qlib_dir}")

    def dump_single_file(self, file_path: str, symbol: str = None):
        """转换单个文件"""
        file_path = Path(file_path)
        
        if not file_path.exists():
            logger.error(f"文件不存在: {file_path}")
            return
        
        if not symbol:
            symbol = self.get_symbol_from_file(file_path)
        
        logger.info(f"转换单个文件: {file_path} -> {symbol}")
        
        try:
            df = self._get_source_data(file_path)
            if not df.empty:
                self._dump_bin(df, file_path, symbol)
                logger.info(f"成功转换文件: {file_path}")
            else:
                logger.warning(f"文件为空: {file_path}")
                
        except Exception as e:
            logger.error(f"转换文件失败: {e}")


class DumpBinanceRun:
    """Binance数据转换运行器"""
    
    def dump_all(
        self,
        csv_path: str,
        qlib_dir: str,
        freq: str = "day",
        max_workers: int = 16,
        include_fields: str = "open,high,low,close,volume,quote_volume",
        exclude_fields: str = "",
        symbol_field_name: str = "symbol",
        date_field_name: str = "date",
        limit_nums: int = None,
    ):
        """
        转换所有Binance CSV数据为qlib格式
        
        Parameters
        ----------
        csv_path: str
            CSV数据目录路径
        qlib_dir: str
            qlib输出目录路径
        freq: str
            数据频率，"day"表示日线，"1min"表示分钟线
        max_workers: int
            并发工作线程数
        include_fields: str
            包含的字段，逗号分隔
        exclude_fields: str
            排除的字段，逗号分隔
        symbol_field_name: str
            交易对字段名
        date_field_name: str
            日期字段名
        limit_nums: int
            限制处理的文件数量（调试用）
            
        Examples
        --------
        # 转换日线数据
        python binance_dump_bin.py dump_all --csv_path ~/.qlib/binance_data/normalize/1d --qlib_dir ~/.qlib/qlib_data/binance_crypto --freq day
        
        # 转换小时数据
        python binance_dump_bin.py dump_all --csv_path ~/.qlib/binance_data/normalize/1h --qlib_dir ~/.qlib/qlib_data/binance_crypto_1h --freq 1h
        
        # 只转换前10个文件（调试）
        python binance_dump_bin.py dump_all --csv_path ~/.qlib/binance_data/normalize/1d --qlib_dir ~/.qlib/qlib_data/binance_test --limit_nums 10
        """
        
        dumper = DumpBinance(
            csv_path=csv_path,
            qlib_dir=qlib_dir,
            freq=freq,
            max_workers=max_workers,
            include_fields=include_fields,
            exclude_fields=exclude_fields,
            symbol_field_name=symbol_field_name,
            date_field_name=date_field_name,
            limit_nums=limit_nums,
        )
        
        dumper.dump_all()

    def dump_single(
        self,
        file_path: str,
        qlib_dir: str,
        symbol: str = None,
        freq: str = "day",
        include_fields: str = "open,high,low,close,volume,quote_volume",
    ):
        """
        转换单个CSV文件
        
        Parameters
        ----------
        file_path: str
            单个CSV文件路径
        qlib_dir: str
            qlib输出目录
        symbol: str
            交易对符号，如不提供则从文件名推断
        freq: str
            数据频率
        include_fields: str
            包含的字段
            
        Examples
        --------
        # 转换单个文件
        python binance_dump_bin.py dump_single --file_path ./BTCUSDT.csv --qlib_dir ~/.qlib/qlib_data/test --symbol BTCUSDT
        """
        
        dumper = DumpBinance(
            csv_path=str(Path(file_path).parent),  # 使用文件的父目录
            qlib_dir=qlib_dir,
            freq=freq,
            include_fields=include_fields,
        )
        
        dumper.dump_single_file(file_path, symbol)

    def validate_data(self, qlib_dir: str, symbols: str = "BTCUSDT,ETHUSDT"):
        """
        验证转换后的qlib数据
        
        Parameters
        ----------
        qlib_dir: str
            qlib数据目录
        symbols: str
            要验证的交易对，逗号分隔
        """
        try:
            import qlib
            from qlib.data import D
            
            # 初始化qlib
            qlib.init(provider_uri=qlib_dir, region="us")
            
            symbol_list = symbols.split(',')
            
            for symbol in symbol_list:
                try:
                    # 获取数据
                    data = D.features(
                        D.instruments([symbol]), 
                        ["$open", "$high", "$low", "$close", "$volume"],
                        freq="day"
                    )
                    
                    if data.empty:
                        logger.warning(f"交易对 {symbol} 无数据")
                        continue
                    
                    logger.info(f"交易对 {symbol}: {len(data)} 条记录")
                    logger.info(f"日期范围: {data.index.min()} 到 {data.index.max()}")
                    logger.info(f"最新价格: {data['$close'].iloc[-1]:.4f}")
                    
                    # 检查数据完整性
                    missing_data = data.isnull().sum()
                    if missing_data.sum() > 0:
                        logger.warning(f"交易对 {symbol} 存在缺失数据: {missing_data}")
                    else:
                        logger.info(f"交易对 {symbol} 数据完整")
                    
                    print(f"\n{symbol} 最近5天数据:")
                    print(data.tail().round(4))
                    print("-" * 50)
                    
                except Exception as e:
                    logger.error(f"验证交易对 {symbol} 失败: {e}")
            
        except Exception as e:
            logger.error(f"数据验证失败: {e}")


if __name__ == "__main__":
    fire.Fire(DumpBinanceRun)