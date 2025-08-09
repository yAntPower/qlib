#!/usr/bin/env python3
"""
通用加密货币分析系统启动脚本
使用方法: python start_crypto_analyzer.py

⚠️  重要提醒：
推荐使用专用启动器以获得更好的体验：
1. okx_integration_starter.py - OKX集成方案（最推荐）
2. binance_analyzer_starter.py - Binance方案 
3. start_crypto_analyzer.py - 通用兼容方案（本文件）

本脚本为通用兼容模式，主要用于测试和向后兼容。
兼容数据源：Binance（推荐OHLC）、TradingView（付费）、CoinGecko（仅价格）
"""

import sys
import time
import threading
from pathlib import Path

# 添加qlib路径
CUR_DIR = Path(__file__).resolve().parent
sys.path.append(str(CUR_DIR.parent.parent.parent))

from qlib.contrib.strategy.crypto_realtime_analyzer import CryptoRealtimeAnalyzer
from qlib.contrib.strategy.go_communication import GoTradingInterface

def main():
    print("🚀 启动加密货币实时分析系统...")
    
    # 配置参数
    # 推荐方案：使用okx_integration_starter.py 或 binance_analyzer_starter.py
    # 以下配置为通用兼容模式，推荐使用专用启动器
    
    # 方案1: 使用Binance数据（推荐OHLC完整数据）
    DATA_PATH = "~/.qlib/qlib_data/crypto_binance_data"  # 使用Binance数据
    SYMBOLS = ["BTCUSDT", "ETHUSDT", "ADAUSDT", "DOTUSDT"]  # Binance符号格式
    
    # 方案2: 使用CoinGecko数据（仅价格数据，回测受限）
    # DATA_PATH = "~/.qlib/qlib_data/crypto_data"  # 使用CoinGecko数据
    # SYMBOLS = ["bitcoin", "ethereum", "cardano", "polkadot"]  # CoinGecko符号格式
    
    # 方案3: 使用TradingView数据（需付费订阅）
    # DATA_PATH = "~/.qlib/qlib_data/crypto_tv_data"  # 如果使用TradingView数据
    # SYMBOLS = ["BTCUSDT", "ETHUSDT", "ADAUSDT", "DOTUSDT"]  # TradingView符号格式
    
    OUTPUT_DIR = "/tmp/qlib_crypto_signals"
    GO_CLIENT_PATH = "/tmp/crypto_client.go"
    
    try:
        # 1. 创建实时分析器
        print("📊 初始化分析器...")
        analyzer = CryptoRealtimeAnalyzer(
            qlib_provider_uri=DATA_PATH,
            websocket_port=8765,
            update_interval=30,  # 30秒更新
        )
        
        # 2. 创建Go通信接口
        print("🔗 初始化Go通信接口...")
        go_interface = GoTradingInterface(
            analyzer=analyzer,
            http_port=8080,
            output_dir=OUTPUT_DIR,
            redis_config={"host": "localhost", "port": 6379, "db": 0},  # 可选
        )
        
        # 3. 获取客户端集成信息
        print("📝 获取客户端集成信息...")
        client_info = go_interface.get_client_integration_info()
        print(f"    {client_info['integration_note']}")
        
        # 4. 启动HTTP服务器
        print("🌐 启动HTTP API服务器 (端口 8080)...")
        go_interface.start_http_server_thread()
        
        # 5. 启动WebSocket服务器
        print("🔌 启动WebSocket服务器 (端口 8765)...")
        ws_thread = threading.Thread(target=analyzer.start_websocket_server, daemon=True)
        ws_thread.start()
        
        # 6. 启动实时分析
        print(f"🎯 开始分析交易对: {SYMBOLS}")
        analyzer.start_analysis(SYMBOLS)
        
        # 7. 系统运行信息
        print("\n✅ 系统启动成功！")
        print(f"📡 HTTP API: http://localhost:8080")
        print(f"🔌 WebSocket: ws://localhost:8765") 
        print(f"📁 信号输出目录: {OUTPUT_DIR}")
        print(f"🐹 Go客户端: 请参考okx_strategy项目")
        print("\n📋 可用API端点:")
        print("  GET  /health          - 健康检查")
        print("  GET  /signals/latest  - 获取最新信号")
        print("  GET  /signals         - 获取指定符号信号")
        print("  POST /analyze         - 触发分析")
        
        print("\n🔄 系统正在运行中... (按 Ctrl+C 停止)")
        
        # 8. 保持程序运行
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n⏹️  收到停止信号，正在关闭系统...")
        analyzer.stop_analysis()
        print("✅ 系统已停止")
        
    except Exception as e:
        print(f"❌ 系统启动失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()