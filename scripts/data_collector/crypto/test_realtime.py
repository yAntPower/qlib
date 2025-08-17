#!/usr/bin/env python3
"""测试实时数据获取"""

import requests
import pandas as pd
from datetime import datetime

def fetch_latest_klines(symbol, interval="1h", limit=5):
    """获取最新K线数据"""
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        klines = response.json()
        
        # 打印最新的几条K线
        print(f"\n{symbol} 最新 {limit} 条 {interval} K线：")
        for kline in klines[-3:]:  # 只显示最后3条
            timestamp = datetime.fromtimestamp(kline[0]/1000)
            open_price = float(kline[1])
            high = float(kline[2])
            low = float(kline[3])
            close = float(kline[4])
            volume = float(kline[5])
            
            print(f"  {timestamp}: O={open_price:.2f}, H={high:.2f}, L={low:.2f}, C={close:.2f}, V={volume:.2f}")
        
        return True
        
    except Exception as e:
        print(f"获取 {symbol} 失败: {e}")
        return False

# 测试主要交易对
symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

print("=" * 60)
print("测试实时数据获取")
print("=" * 60)

for symbol in symbols:
    fetch_latest_klines(symbol, "1h", 5)

print("\n✅ 实时数据获取测试完成")