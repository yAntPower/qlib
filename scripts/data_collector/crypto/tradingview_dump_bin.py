#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
TradingView crypto data dumper with OHLC support for backtesting
This script converts TradingView crypto CSV data to qlib binary format with full OHLC support
"""

import sys
from pathlib import Path
import pandas as pd
from loguru import logger

# Add parent directories to path
CUR_DIR = Path(__file__).resolve().parent
sys.path.append(str(CUR_DIR.parent.parent))
sys.path.append(str(CUR_DIR.parent.parent.parent))

from scripts.dump_bin import DumpDataBase
import fire


class TradingViewCryptoDumper(DumpDataBase):
    """TradingView crypto data dumper with OHLC support"""
    
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
        TradingView crypto data dumper
        
        Parameters
        ----------
        csv_path: str
            TradingView crypto data path or directory
        qlib_dir: str
            qlib(dump) data directory
        backup_dir: str, default None
            if backup_dir is not None, backup qlib_dir to backup_dir
        freq: str, default "day"
            transaction frequency (day, 1min, etc.)
        max_workers: int, default 16
            number of threads
        date_field_name: str, default "date"
            the name of the date field in the csv
        file_suffix: str, default ".csv"
            file suffix
        symbol_field_name: str, default "symbol"
            symbol field name
        include_fields: str
            dump fields (comma-separated), e.g., "open,high,low,close,volume"
        exclude_fields: str
            fields not dumped (comma-separated)
        limit_nums: int
            Use when debugging, default None
        """
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
        
        # Default OHLC fields for crypto if not specified
        if not self._include_fields:
            self._include_fields = ("open", "high", "low", "close", "volume")
            logger.info(f"Using default OHLC fields: {self._include_fields}")

    def _read_csv(self, file_path: Path) -> pd.DataFrame:
        """Read and process TradingView crypto CSV data"""
        try:
            df = pd.read_csv(file_path)
            
            # Validate required fields
            required_fields = [self.date_field_name, self.symbol_field_name]
            missing_fields = [field for field in required_fields if field not in df.columns]
            if missing_fields:
                logger.error(f"Missing required fields in {file_path}: {missing_fields}")
                return pd.DataFrame()
            
            # Ensure OHLC fields exist
            ohlc_fields = ["open", "high", "low", "close", "volume"]
            for field in ohlc_fields:
                if field not in df.columns:
                    logger.warning(f"Missing OHLC field '{field}' in {file_path}, setting to 0")
                    df[field] = 0.0
            
            # Convert date column
            df[self.date_field_name] = pd.to_datetime(df[self.date_field_name])
            
            # Filter fields
            if self._include_fields:
                # Include specified fields + required fields
                keep_fields = list(self._include_fields) + [self.date_field_name, self.symbol_field_name]
                keep_fields = [f for f in keep_fields if f in df.columns]
                df = df[keep_fields]
            
            if self._exclude_fields:
                # Exclude specified fields (but keep required fields)
                exclude_fields = [f for f in self._exclude_fields if f not in required_fields]
                df = df.drop(columns=exclude_fields, errors='ignore')
            
            logger.info(f"Loaded {len(df)} records from {file_path} with columns: {list(df.columns)}")
            return df
            
        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")
            return pd.DataFrame()

    def _validate_ohlc_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Validate and clean OHLC data"""
        if df.empty:
            return df
            
        # Check for OHLC consistency
        if all(col in df.columns for col in ['open', 'high', 'low', 'close']):
            # Ensure high >= max(open, close) and low <= min(open, close)
            df.loc[df['high'] < df[['open', 'close']].max(axis=1), 'high'] = df[['open', 'close']].max(axis=1)
            df.loc[df['low'] > df[['open', 'close']].min(axis=1), 'low'] = df[['open', 'close']].min(axis=1)
            
            # Remove rows with invalid data (all zeros or negative prices)
            invalid_mask = (
                (df[['open', 'high', 'low', 'close']] <= 0).all(axis=1) |
                df[['open', 'high', 'low', 'close']].isna().all(axis=1)
            )
            if invalid_mask.sum() > 0:
                logger.warning(f"Removing {invalid_mask.sum()} rows with invalid OHLC data")
                df = df[~invalid_mask]
        
        return df

    def dump_all(self):
        """Dump all TradingView crypto data to qlib format"""
        logger.info("Starting TradingView crypto data dump with OHLC support...")
        
        # Create directories
        self._calendars_dir.mkdir(parents=True, exist_ok=True)
        self._features_dir.mkdir(parents=True, exist_ok=True)
        self._instruments_dir.mkdir(parents=True, exist_ok=True)
        
        # Process all CSV files
        all_data = []
        for csv_file in self.csv_files:
            df = self._read_csv(csv_file)
            if not df.empty:
                df = self._validate_ohlc_data(df)
                all_data.append(df)
        
        if not all_data:
            logger.error("No valid data found in CSV files")
            return
        
        # Combine all data
        combined_df = pd.concat(all_data, ignore_index=True)
        logger.info(f"Combined dataset: {len(combined_df)} records, {combined_df[self.symbol_field_name].nunique()} symbols")
        
        # Group by symbol and dump
        symbols = combined_df[self.symbol_field_name].unique()
        logger.info(f"Processing {len(symbols)} symbols...")
        
        instruments_data = []
        
        for symbol in symbols:
            symbol_data = combined_df[combined_df[self.symbol_field_name] == symbol].copy()
            symbol_data = symbol_data.sort_values(self.date_field_name)
            
            if len(symbol_data) == 0:
                continue
                
            # Format dates
            symbol_data[self.date_field_name] = symbol_data[self.date_field_name].dt.strftime(self.calendar_format)
            
            # Save to binary
            self._dump_symbol_data(symbol, symbol_data)
            
            # Track instrument info
            instruments_data.append({
                'symbol': symbol,
                self.INSTRUMENTS_START_FIELD: symbol_data[self.date_field_name].min(),
                self.INSTRUMENTS_END_FIELD: symbol_data[self.date_field_name].max(),
            })
        
        # Save instruments list
        self._save_instruments(instruments_data)
        
        # Generate calendar
        self._save_calendar(combined_df)
        
        logger.info(f"Successfully dumped TradingView crypto data to {self.qlib_dir}")
        logger.info(f"Supported features: {self._include_fields}")
        logger.info("Data is now ready for qlib backtesting!")

    def _dump_symbol_data(self, symbol: str, data: pd.DataFrame):
        """Dump individual symbol data to binary format"""
        symbol_dir = self._features_dir / symbol.lower()
        symbol_dir.mkdir(parents=True, exist_ok=True)
        
        # Save each field as binary
        for field in self._include_fields:
            if field in data.columns:
                field_data = data.set_index(self.date_field_name)[field]
                field_file = symbol_dir / f"{field}.bin"
                
                # Convert to numpy and save
                try:
                    field_data.to_frame().to_feather(field_file)
                    logger.debug(f"Saved {symbol}:{field} to {field_file}")
                except Exception as e:
                    logger.error(f"Failed to save {symbol}:{field}: {e}")

    def _save_instruments(self, instruments_data: list):
        """Save instruments list"""
        instruments_df = pd.DataFrame(instruments_data)
        instruments_file = self._instruments_dir / self.INSTRUMENTS_FILE_NAME
        
        instruments_df.to_csv(
            instruments_file,
            sep=self.INSTRUMENTS_SEP,
            header=False,
            index=False
        )
        logger.info(f"Saved {len(instruments_data)} instruments to {instruments_file}")

    def _save_calendar(self, data: pd.DataFrame):
        """Generate and save trading calendar"""
        # Get all unique dates
        all_dates = data[self.date_field_name].dt.strftime(self.calendar_format).unique()
        calendar_df = pd.DataFrame(sorted(all_dates), columns=[self.date_field_name])
        
        calendar_file = self._calendars_dir / f"{self.freq}.txt"
        calendar_df.to_csv(calendar_file, index=False, header=False)
        logger.info(f"Saved calendar with {len(calendar_df)} trading days to {calendar_file}")


def main():
    """Main entry point"""
    fire.Fire(TradingViewCryptoDumper)


if __name__ == "__main__":
    main()