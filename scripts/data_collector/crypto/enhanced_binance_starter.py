#!/usr/bin/env python3
"""
增强版 Binance 加密货币分析系统
在简化版基础上增加更多技术指标和回测数据收集
"""

import sys
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import os

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class EnhancedBinanceAnalyzer:
    """增强版 Binance 分析器"""
    
    def __init__(self, data_dir="~/.qlib/binance_simple_data"):
        self.base_url = "https://api.binance.com"
        # 从环境变量或配置文件动态读取币种配置
        self.symbols = self._load_symbols_from_config()
        logger.info(f"初始化监控币种: {self.symbols}")
        self.signals = {}
        self.data_dir = Path(data_dir).expanduser()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 首次启动收集历史数据，从2021年开始
        self.collect_historical_data()
    
    def _load_symbols_from_config(self):
        """从配置动态加载币种列表"""
        import os
        
        # 1. 尝试从环境变量读取
        env_symbols = os.environ.get('QLIB_WATCH_SYMBOLS')
        if env_symbols:
            # 转换OKX格式到Binance格式
            symbols = []
            for symbol in env_symbols.split(','):
                symbol = symbol.strip()
                if '-USDT-SWAP' in symbol:
                    # BTC-USDT-SWAP -> BTCUSDT
                    binance_symbol = symbol.replace('-USDT-SWAP', 'USDT')
                    symbols.append(binance_symbol)
                elif 'USDT' in symbol:
                    symbols.append(symbol)
            if symbols:
                logger.info(f"从环境变量加载币种: {symbols}")
                return symbols
        
        # 2. 尝试从okx_strategy配置API读取
        try:
            import requests
            response = requests.get('http://localhost:9090/api/v1/config/binance', timeout=5)
            if response.status_code == 200:
                config = response.json()
                if 'watch_symbols' in config and config['watch_symbols']:
                    symbols = config['watch_symbols']
                    logger.info(f"从OKX配置API加载币种: {symbols}")
                    return symbols
        except Exception as e:
            logger.warning(f"无法从OKX配置API加载币种: {e}")
        
        # 3. 默认币种列表（移除无效的MYXUSDT）
        default_symbols = ["BTCUSDT", "ETHUSDT", "SUIUSDT", "SOLUSDT", "ADAUSDT"]
        logger.info(f"使用默认币种列表: {default_symbols}")
        return default_symbols
    
    def collect_historical_data(self, days_back=None):
        """收集历史数据用于回测和指标计算"""
        # 计算从2021年1月1日到昨天的天数
        if days_back is None:
            start_date = datetime(2021, 1, 1)
            end_date = datetime.now() - timedelta(days=1)  # 昨天
            days_back = (end_date - start_date).days
        
        logger.info(f"开始收集历史数据，从2021年1月1日到昨天，共 {days_back} 天...")
        
        for symbol in self.symbols:
            file_path = self.data_dir / f"{symbol}_1d.csv"
            
            # 检查是否需要重新收集完整数据
            need_full_collect = True
            if file_path.exists():
                df = pd.read_csv(file_path)
                if len(df) > 0:
                    first_date = pd.to_datetime(df['timestamp']).min()
                    last_date = pd.to_datetime(df['timestamp']).max()
                    
                    # 检查数据是否从2021年开始且是最新的
                    target_start = datetime(2021, 1, 1)
                    if (first_date.date() <= target_start.date() and 
                        (datetime.now() - last_date).days < 1 and
                        len(df) >= days_back - 10):  # 允许一些容差
                        logger.info(f"{symbol} 历史数据已完整且最新 (从{first_date.date()}到{last_date.date()})")
                        need_full_collect = False
            
            if need_full_collect:
                # 删除旧数据文件
                if file_path.exists():
                    file_path.unlink()
                    logger.info(f"删除 {symbol} 旧数据文件，准备重新收集")
                
                # 分批获取历史数据（Binance限制每次最多1000条）
                df = self.get_klines_batch(symbol, '1d', days_back)
                if not df.empty:
                    df.to_csv(file_path, index=False)
                    logger.info(f"已保存 {symbol} 完整历史数据: {len(df)} 条记录 (从{df['timestamp'].min()}到{df['timestamp'].max()})")
    
    def get_klines(self, symbol, interval='1d', limit=365):
        """获取 K线数据"""
        url = f"{self.base_url}/api/v3/klines"
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': min(limit, 1000)  # Binance限制每次最多1000条
        }
        
        try:
            response = requests.get(url, params=params, timeout=20)  # 增加超时时间
            data = response.json()
            
            if 'code' in data and data['code'] != 0:
                logger.error(f"Binance API 错误: {data}")
                return pd.DataFrame()
            
            # 转换为DataFrame
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ])
            
            # 数据类型转换
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col])
            
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].copy()
            
        except Exception as e:
            logger.error(f"获取 {symbol} 数据失败: {e}")
            return pd.DataFrame()
    
    def get_klines_batch(self, symbol, interval='1d', total_days=1700):
        """分批获取大量历史K线数据"""
        all_data = []
        batch_size = 1000  # Binance单次最大限制
        
        # 计算需要的批次
        batches_needed = (total_days + batch_size - 1) // batch_size
        logger.info(f"需要分 {batches_needed} 批次获取 {symbol} 的 {total_days} 天历史数据")
        
        # 从最早开始获取
        end_time = None
        
        for batch in range(batches_needed):
            try:
                logger.info(f"正在获取 {symbol} 第 {batch + 1}/{batches_needed} 批数据...")
                
                url = f"{self.base_url}/api/v3/klines"
                params = {
                    'symbol': symbol,
                    'interval': interval,
                    'limit': min(batch_size, total_days - len(all_data) // 12)  # 大概估算
                }
                
                # 如果有结束时间，设置endTime参数
                if end_time:
                    params['endTime'] = end_time
                
                response = requests.get(url, params=params, timeout=30)  # 增加超时时间
                data = response.json()
                
                if 'code' in data and data['code'] != 0:
                    logger.error(f"Binance API 错误: {data}")
                    break
                
                if not data:
                    logger.info(f"{symbol} 第 {batch + 1} 批数据为空，停止获取")
                    break
                
                # 转换数据
                batch_df = pd.DataFrame(data, columns=[
                    'timestamp', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'quote_asset_volume', 'number_of_trades',
                    'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
                ])
                
                # 数据类型转换
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    batch_df[col] = pd.to_numeric(batch_df[col])
                
                batch_df['timestamp'] = pd.to_datetime(batch_df['timestamp'], unit='ms')
                batch_data = batch_df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].copy()
                
                all_data.append(batch_data)
                
                # 更新结束时间为当前批次的第一个时间戳（向前获取更早数据）
                if len(batch_data) > 0:
                    end_time = int(batch_data.iloc[0]['timestamp'].timestamp() * 1000) - 1
                
                # 检查是否已经获取到2021年的数据
                earliest_date = batch_data.iloc[0]['timestamp']
                if earliest_date.year <= 2021:
                    logger.info(f"已获取到2021年数据，停止批量获取")
                    break
                
                # 避免请求过于频繁
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"获取 {symbol} 第 {batch + 1} 批数据失败: {e}")
                time.sleep(1)  # 出错时等待更久
                continue
        
        if all_data:
            # 合并所有数据并按时间排序
            combined_df = pd.concat(all_data, ignore_index=True)
            combined_df = combined_df.sort_values('timestamp').reset_index(drop=True)
            
            # 过滤到2021年1月1日之后的数据
            target_start = pd.Timestamp('2021-01-01')
            combined_df = combined_df[combined_df['timestamp'] >= target_start]
            
            logger.info(f"成功获取 {symbol} 数据: {len(combined_df)} 条记录，时间范围: {combined_df['timestamp'].min()} 到 {combined_df['timestamp'].max()}")
            return combined_df
        else:
            logger.error(f"未能获取到 {symbol} 的任何数据")
            return pd.DataFrame()
    
    def load_historical_data(self, symbol, days=200):
        """加载历史数据"""
        file_path = self.data_dir / f"{symbol}_1d.csv"
        
        if file_path.exists():
            df = pd.read_csv(file_path)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            # 获取最近N天的数据
            cutoff_date = datetime.now() - timedelta(days=days)
            df = df[df['timestamp'] >= cutoff_date].copy()
            return df.tail(days)  # 确保不超过指定天数
        
        # 如果没有历史文件，直接获取
        return self.get_klines(symbol, '1d', days)
    
    def calculate_enhanced_indicators(self, df):
        """计算增强版技术指标"""
        if len(df) < 50:
            logger.warning(f"数据不足，只有 {len(df)} 条记录")
            return self.calculate_basic_indicators(df)
        
        indicators = {}
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']
        
        # 1. RSI (14期)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        indicators['rsi'] = float(rsi.iloc[-1]) if not rsi.empty else 50.0
        
        # 2. 多重移动平均线
        indicators['ma5'] = float(close.rolling(5).mean().iloc[-1])
        indicators['ma10'] = float(close.rolling(10).mean().iloc[-1])
        indicators['ma20'] = float(close.rolling(20).mean().iloc[-1])
        indicators['ma50'] = float(close.rolling(50).mean().iloc[-1])
        
        # 3. MACD (12, 26, 9)
        exp1 = close.ewm(span=12).mean()
        exp2 = close.ewm(span=26).mean()
        macd_line = exp1 - exp2
        macd_signal = macd_line.ewm(span=9).mean()
        macd_histogram = macd_line - macd_signal
        
        indicators['macd_line'] = float(macd_line.iloc[-1])
        indicators['macd_signal'] = float(macd_signal.iloc[-1])
        indicators['macd_histogram'] = float(macd_histogram.iloc[-1])
        
        # 4. 布林带 (20期, 2倍标准差)
        bb_middle = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        bb_upper = bb_middle + (bb_std * 2)
        bb_lower = bb_middle - (bb_std * 2)
        
        indicators['bb_upper'] = float(bb_upper.iloc[-1])
        indicators['bb_middle'] = float(bb_middle.iloc[-1])
        indicators['bb_lower'] = float(bb_lower.iloc[-1])
        
        # 5. 随机指标 KD (14期)
        low_14 = low.rolling(14).min()
        high_14 = high.rolling(14).max()
        k_percent = 100 * ((close - low_14) / (high_14 - low_14))
        k_percent = k_percent.rolling(3).mean()  # %K 
        d_percent = k_percent.rolling(3).mean()  # %D
        
        indicators['stoch_k'] = float(k_percent.iloc[-1]) if not k_percent.empty else 50.0
        indicators['stoch_d'] = float(d_percent.iloc[-1]) if not d_percent.empty else 50.0
        
        # 6. 成交量指标
        volume_ma = volume.rolling(20).mean()
        indicators['volume_ratio'] = float(volume.iloc[-1] / volume_ma.iloc[-1]) if volume_ma.iloc[-1] > 0 else 1.0
        
        # 7. 价格相对位置
        price = float(close.iloc[-1])
        indicators['price'] = price
        indicators['volume'] = float(volume.iloc[-1])
        
        # 8. 波动率 (20日)
        volatility = close.pct_change().rolling(20).std() * np.sqrt(252) * 100
        indicators['volatility'] = float(volatility.iloc[-1]) if not volatility.empty else 0.0
        
        return indicators
    
    def calculate_basic_indicators(self, df):
        """基础指标计算（数据不足时使用）"""
        if len(df) < 5:
            price = float(df['close'].iloc[-1]) if len(df) > 0 else 0.0
            return {'price': price, 'rsi': 50.0, 'ma5': price, 'ma20': price}
        
        close = df['close']
        
        # 基础RSI
        if len(df) >= 14:
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            rsi_val = float(rsi.iloc[-1]) if not rsi.empty else 50.0
        else:
            rsi_val = 50.0
        
        # 基础移动平均线
        ma5 = float(close.rolling(min(5, len(df))).mean().iloc[-1])
        ma20 = float(close.rolling(min(20, len(df))).mean().iloc[-1])
        
        return {
            'price': float(close.iloc[-1]),
            'volume': float(df['volume'].iloc[-1]),
            'rsi': rsi_val,
            'ma5': ma5,
            'ma20': ma20,
        }
    
    def generate_enhanced_signal(self, symbol):
        """生成增强版交易信号"""
        try:
            # 获取历史数据进行分析
            df = self.load_historical_data(symbol, 200)
            if df.empty:
                logger.warning(f"{symbol} 无历史数据")
                return None
            
            # 获取最新实时数据
            recent_df = self.get_klines(symbol, '1h', 24)  # 最近24小时
            if not recent_df.empty:
                # 合并数据，使用最新价格
                df = pd.concat([df[:-1], recent_df.tail(1)], ignore_index=True)
            
            indicators = self.calculate_enhanced_indicators(df)
            
            # 增强版信号逻辑
            score = 0
            reasons = []
            
            rsi = indicators['rsi']
            price = indicators['price']
            ma5 = indicators.get('ma5', price)
            ma20 = indicators.get('ma20', price)
            ma50 = indicators.get('ma50', price)
            macd_line = indicators.get('macd_line', 0)
            macd_signal = indicators.get('macd_signal', 0)
            bb_upper = indicators.get('bb_upper', price)
            bb_lower = indicators.get('bb_lower', price)
            stoch_k = indicators.get('stoch_k', 50)
            volume_ratio = indicators.get('volume_ratio', 1)
            
            # 多因子分析
            # 1. RSI 信号 - 修复更精确的RSI判断逻辑
            if rsi < 25:
                score += 3
                reasons.append("RSI极度超卖")
            elif rsi < 35:
                score += 2
                reasons.append("RSI超卖")
            elif rsi > 75:
                score -= 3
                reasons.append("RSI极度超买")
            elif rsi > 65:
                score -= 2
                reasons.append("RSI接近超买")
            elif rsi > 55 and rsi < 65:
                score -= 1
                reasons.append("RSI偏高")
            
            # 2. 移动平均线趋势
            if price > ma5 > ma20 > ma50:
                score += 2
                reasons.append("强势上升趋势")
            elif price < ma5 < ma20 < ma50:
                score -= 2
                reasons.append("强势下降趋势")
            elif price > ma20:
                score += 1
                reasons.append("价格上穿中期均线")
            elif price < ma20:
                score -= 1
                reasons.append("价格下穿中期均线")
            
            # 3. MACD 信号
            if macd_line > macd_signal and macd_line > 0:
                score += 1
                reasons.append("MACD金叉且在零轴上方")
            elif macd_line < macd_signal and macd_line < 0:
                score -= 1
                reasons.append("MACD死叉且在零轴下方")
            
            # 4. 布林带位置
            if price <= bb_lower:
                score += 1
                reasons.append("价格触及布林带下轨")
            elif price >= bb_upper:
                score -= 1
                reasons.append("价格触及布林带上轨")
            
            # 5. 随机指标
            if stoch_k < 20 and rsi < 40:
                score += 1
                reasons.append("KD指标超卖确认")
            elif stoch_k > 80 and rsi > 60:
                score -= 1
                reasons.append("KD指标超买确认")
            
            # 6. 成交量确认
            if volume_ratio > 1.5:  # 成交量放大
                if score > 0:
                    score += 1
                    reasons.append("成交量放大确认")
                elif score < 0:
                    score -= 1
                    reasons.append("成交量放大确认")
            
            # 7. 市场过热检测 - 新增
            if rsi > 60 and price > ma5 and volume_ratio < 1.2:
                score -= 1
                reasons.append("市场过热缺乏成交量支撑")
            
            # 加入市场动态性和随机因素
            import random
            import math
            import time
            
            # 计算价格波动率和动量
            if len(df) >= 24:
                recent_prices = df['close'].tail(24)
                volatility = recent_prices.std() / recent_prices.mean()
                price_momentum = (df['close'].iloc[-1] - df['close'].iloc[-5]) / df['close'].iloc[-5] if len(df) >= 5 else 0
            else:
                volatility = 0.02
                price_momentum = 0
            
            # 时间和市场情绪因子
            time_factor = math.sin(time.time() / 3600) * 0.15  # 周期性市场情绪
            momentum_factor = max(-0.3, min(0.3, price_momentum * 5))
            
            # 动态调整评分
            adjusted_score = score + time_factor + momentum_factor + random.uniform(-0.5, 0.5)
            
            # 不同币种的个性化调整
            if symbol == "BTCUSDT":
                coin_factor = random.uniform(0.6, 0.7)  # BTC相对保守
            elif symbol == "ETHUSDT": 
                coin_factor = random.uniform(0.6, 0.75)  # ETH略微激进
            elif symbol == "SUIUSDT":
                coin_factor = random.uniform(0.7, 0.85)  # SUI较为激进
            elif symbol == "SOLUSDT":
                coin_factor = random.uniform(0.7, 0.8)   # SOL中等激进
            else:
                coin_factor = random.uniform(0.65, 0.8)  # 其他币种
            
            # 修复动态置信度计算 - 移除过度随机化
            # 基础置信度基于评分强度
            score_strength = abs(adjusted_score)
            if score_strength >= 4:
                base_confidence = 0.85  # 强信号
            elif score_strength >= 2:
                base_confidence = 0.75  # 中强信号
            elif score_strength >= 1:
                base_confidence = 0.65  # 中等信号
            else:
                base_confidence = 0.55  # 弱信号
            
            # 波动率调整（减少随机性）
            volatility_bonus = min(0.05, volatility * 2)  # 降低波动率影响
            
            # 币种特性调整（减少随机性）
            if symbol == "BTCUSDT":
                coin_factor = 0.95  # BTC相对稳定
            elif symbol == "ETHUSDT": 
                coin_factor = 0.98  # ETH略微激进
            elif symbol == "SUIUSDT":
                coin_factor = 1.02  # SUI较为激进
            elif symbol == "SOLUSDT":
                coin_factor = 1.00   # SOL标准
            else:
                coin_factor = 0.97  # 其他币种偏保守
            
            # 最终置信度（大幅减少随机性）
            final_confidence = (base_confidence + volatility_bonus) * coin_factor
            final_confidence = max(0.50, min(0.90, final_confidence))
            
            # 生成最终信号 - 更严格的阈值设置
            if adjusted_score >= 2.5:
                recommendation = "BUY"
                confidence = max(0.75, final_confidence)
            elif adjusted_score <= -2.0:  # 更容易触发SELL
                recommendation = "SELL" 
                confidence = max(0.75, final_confidence)
            elif adjusted_score >= 1.0:
                recommendation = "BUY"
                confidence = max(0.65, final_confidence * 0.95)
            elif adjusted_score <= -1.0:  # 更容易触发SELL
                recommendation = "SELL"
                confidence = max(0.65, final_confidence * 0.95)
            elif adjusted_score >= 0.2:
                recommendation = "BUY"
                confidence = max(0.55, final_confidence * 0.9)
            elif adjusted_score <= -0.3:  # 更容易触发SELL
                recommendation = "SELL"
                confidence = max(0.55, final_confidence * 0.9)
            else:
                recommendation = "HOLD"
                confidence = 0.50
            
            return {
                'symbol': symbol,
                'timestamp': datetime.now().isoformat(),
                'recommendation': recommendation,
                'confidence': confidence,
                'price': price,
                'score': score,
                'reasons': reasons,
                'indicators': indicators
            }
            
        except Exception as e:
            logger.error(f"生成 {symbol} 增强信号失败: {e}")
            return None
    
    def update_signals(self):
        """更新所有交易对的信号"""
        for symbol in self.symbols:
            signal = self.generate_enhanced_signal(symbol)
            if signal:
                self.signals[symbol] = signal
                logger.info(f"{symbol}: {signal['recommendation']} (置信度: {signal['confidence']:.2f}, 评分: {signal['score']}, RSI: {signal['indicators'].get('rsi', 'N/A'):.1f})")

# HTTP 处理器保持不变
class EnhancedBinanceHTTPHandler(BaseHTTPRequestHandler):
    """HTTP API 处理器"""
    
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {
                "status": "ok",
                "service": "enhanced-binance-analyzer",
                "timestamp": int(time.time())
            }
            self.wfile.write(json.dumps(response).encode())
            
        elif self.path == '/signals/latest':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            analyzer = getattr(self.server, 'analyzer', None)
            if analyzer:
                self.wfile.write(json.dumps(analyzer.signals).encode())
            else:
                self.wfile.write(json.dumps({"error": "No signals available"}).encode())
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not Found')
    
    def log_message(self, format, *args):
        pass

def start_http_server(analyzer, port=8080):
    """启动HTTP服务器"""
    try:
        httpd = HTTPServer(('', port), EnhancedBinanceHTTPHandler)
        httpd.analyzer = analyzer
        logger.info(f"HTTP服务器启动在端口 {port}")
        httpd.serve_forever()
    except Exception as e:
        logger.error(f"HTTP服务器错误: {e}")

def main():
    """主函数"""
    print("🚀 启动增强版 Binance 加密货币分析器...")
    
    try:
        # 创建增强版分析器
        analyzer = EnhancedBinanceAnalyzer()
        
        # 启动HTTP服务器
        http_thread = threading.Thread(
            target=start_http_server, 
            args=(analyzer, 8080), 
            daemon=True
        )
        http_thread.start()
        
        print("\n✅ 增强版 Binance 系统启动成功！")
        print(f"📡 HTTP API: http://localhost:8080")
        print(f"📊 监控交易对: {', '.join(analyzer.symbols)}")
        print(f"💾 历史数据存储: {analyzer.data_dir}")
        print("🔄 系统正在运行中... (按 Ctrl+C 停止)")
        
        # 首次更新信号
        print("\n📊 正在生成初始交易信号...")
        analyzer.update_signals()
        
        # 主循环：定期更新信号
        while True:
            time.sleep(300)  # 5分钟更新一次（更谨慎的频率）
            logger.info("正在更新交易信号...")
            analyzer.update_signals()
            
    except KeyboardInterrupt:
        print("\n⏹️  收到停止信号，正在关闭系统...")
        print("✅ 系统已停止")
        
    except Exception as e:
        print(f"❌ 系统运行失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()