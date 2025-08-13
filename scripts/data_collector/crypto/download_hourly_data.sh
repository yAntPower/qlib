#!/bin/bash

# 下载Binance小时级历史数据

set -e

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}[INFO]${NC} 开始下载Binance小时级历史数据..."

# 激活虚拟环境
if [ -f "/home/ant/project/.venv/bin/activate" ]; then
    source "/home/ant/project/.venv/bin/activate"
    PYTHON_CMD="python"
else
    PYTHON_CMD="python3"
fi

# 创建下载脚本
cat > /tmp/download_hourly_data.py << 'EOF'
import requests, pandas as pd, os, sys
from datetime import datetime, timedelta
from pathlib import Path

def download_symbol_data(symbol, start_date, end_date, interval, save_dir):
    session = requests.Session()
    # 使用代理
    http_proxy = os.environ.get('http_proxy')
    if http_proxy:
        session.proxies = {'http': http_proxy, 'https': http_proxy}
    
    url = "https://api.binance.com/api/v3/klines"
    all_data = []
    
    # 小时数据每次获取30天
    batch_days = 30
    
    current_start = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    
    print(f"下载 {symbol} 从 {start_date} 到 {end_date}...")
    
    while current_start < end_dt:
        current_end = min(current_start + timedelta(days=batch_days), end_dt)
        start_ms = int(current_start.timestamp() * 1000)
        end_ms = int(current_end.timestamp() * 1000)
        
        params = {'symbol': symbol, 'interval': interval, 'startTime': start_ms, 'endTime': end_ms, 'limit': 1000}
        
        try:
            response = session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data:
                all_data.extend(data)
                print(f"  获取 {len(data)} 条记录 ({current_start.date()} - {current_end.date()})")
            
            current_start = current_end + timedelta(days=1)
            
        except Exception as e:
            print(f"  错误: {e}")
            current_start = current_end + timedelta(days=1)
            continue
    
    if not all_data:
        return False
        
    columns = ['open_time', 'open', 'high', 'low', 'close', 'volume', 
              'close_time', 'quote_volume', 'trades', 'taker_buy_volume', 
              'taker_buy_quote_volume', 'ignore']
    
    df = pd.DataFrame(all_data, columns=columns)
    df['date'] = pd.to_datetime(df['open_time'], unit='ms')
    df = df[['date', 'open', 'high', 'low', 'close', 'volume']].copy()
    
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col])
    
    # 去重
    df = df.drop_duplicates(subset=['date'])
    df = df.sort_values('date')
    
    Path(save_dir).mkdir(parents=True, exist_ok=True)
    df.to_csv(f"{save_dir}/{symbol}.csv", index=False)
    print(f"✓ {symbol}: {len(df)} 条记录")
    return True

# 配置
save_dir = os.path.expanduser("~/.qlib/binance_hourly_data")
symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'ADAUSDT', 'SUIUSDT']
start_date = "2023-01-01"
end_date = datetime.now().strftime("%Y-%m-%d")

print(f"保存目录: {save_dir}")
print(f"时间范围: {start_date} 到 {end_date}")
print("")

success = 0
for symbol in symbols:
    if download_symbol_data(symbol, start_date, end_date, '1h', save_dir):
        success += 1

print(f"\n完成: {success}/{len(symbols)} 个交易对")
exit(0 if success >= 3 else 1)
EOF

# 执行下载
$PYTHON_CMD /tmp/download_hourly_data.py
RESULT=$?

# 清理
rm -f /tmp/download_hourly_data.py

if [ $RESULT -eq 0 ]; then
    echo -e "${GREEN}[SUCCESS]${NC} 小时数据下载完成！"
    echo -e "${BLUE}[INFO]${NC} 数据保存在: ~/.qlib/binance_hourly_data/"
else
    echo -e "${YELLOW}[WARNING]${NC} 部分数据下载失败"
fi

exit $RESULT