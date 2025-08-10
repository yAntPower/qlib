#!/usr/bin/env python3
"""
简化版加密货币分析器
用于在 qlib 环境问题时临时使用
"""

import json
import time
import threading
import logging
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import socketserver
import random
import os

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SimpleCryptoAnalyzer:
    """简化版加密货币分析器"""
    
    def __init__(self, http_port=8080, websocket_port=8765):
        self.http_port = http_port
        self.websocket_port = websocket_port
        self.running = False
        self.signals = {}
        
        # 模拟分析数据
        self.symbols = ["BTCUSDT", "ETHUSDT", "ADAUSDT", "DOTUSDT"]
        
    def generate_mock_signal(self, symbol):
        """生成模拟交易信号"""
        # 简单的随机信号生成（实际应用中应该是复杂的ML模型）
        confidence = random.uniform(0.6, 0.9)
        signal_type = random.choice(["buy", "sell", "hold"])
        
        return {
            "symbol": symbol,
            "signal": signal_type,
            "confidence": confidence,
            "price": random.uniform(20000, 70000) if "BTC" in symbol else random.uniform(1000, 4000),
            "timestamp": datetime.now().isoformat(),
            "source": "simple_analyzer"
        }
    
    def update_signals(self):
        """定期更新信号"""
        while self.running:
            try:
                for symbol in self.symbols:
                    self.signals[symbol] = self.generate_mock_signal(symbol)
                
                logger.info(f"Updated signals for {len(self.symbols)} symbols")
                time.sleep(30)  # 30秒更新一次
                
            except Exception as e:
                logger.error(f"Error updating signals: {e}")
                time.sleep(5)
    
    def start_analysis(self):
        """启动分析"""
        self.running = True
        logger.info("Starting signal analysis...")
        
        # 启动信号更新线程
        signal_thread = threading.Thread(target=self.update_signals, daemon=True)
        signal_thread.start()
        
        return True

class AnalyzerHTTPRequestHandler(BaseHTTPRequestHandler):
    """HTTP请求处理器"""
    
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {
                "status": "ok",
                "service": "simple-crypto-analyzer",
                "timestamp": int(time.time())
            }
            self.wfile.write(json.dumps(response).encode())
            
        elif self.path == '/signals/latest':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            # 获取最新信号
            latest_signals = getattr(self.server, 'analyzer', None)
            if latest_signals and hasattr(latest_signals, 'signals'):
                self.wfile.write(json.dumps(latest_signals.signals).encode())
            else:
                self.wfile.write(json.dumps({"error": "No signals available"}).encode())
                
        elif self.path.startswith('/signals'):
            # 处理特定符号的信号请求
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            analyzer = getattr(self.server, 'analyzer', None)
            if analyzer and hasattr(analyzer, 'signals'):
                self.wfile.write(json.dumps(analyzer.signals).encode())
            else:
                self.wfile.write(json.dumps({"error": "No signals available"}).encode())
                
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not Found')
    
    def do_POST(self):
        if self.path == '/analyze':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            response = {
                "status": "triggered",
                "message": "Analysis triggered successfully"
            }
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not Found')
    
    def log_message(self, format, *args):
        # 减少HTTP服务器日志输出
        pass

def start_http_server(analyzer, port=8080):
    """启动HTTP服务器"""
    try:
        handler = AnalyzerHTTPRequestHandler
        httpd = HTTPServer(('', port), handler)
        httpd.analyzer = analyzer  # 将分析器实例传递给服务器
        
        logger.info(f"HTTP server starting on port {port}")
        httpd.serve_forever()
        
    except Exception as e:
        logger.error(f"HTTP server error: {e}")

def main():
    """主函数"""
    print("🚀 启动简化版加密货币分析器...")
    
    try:
        # 创建分析器实例
        analyzer = SimpleCryptoAnalyzer(http_port=8080, websocket_port=8765)
        
        # 启动分析
        analyzer.start_analysis()
        
        # 启动HTTP服务器
        print("🌐 启动HTTP API服务器 (端口 8080)...")
        http_thread = threading.Thread(
            target=start_http_server, 
            args=(analyzer, 8080), 
            daemon=True
        )
        http_thread.start()
        
        print("\n✅ 简化版系统启动成功！")
        print(f"📡 HTTP API: http://localhost:8080")
        print(f"📋 可用API端点:")
        print("  GET  /health          - 健康检查")
        print("  GET  /signals/latest  - 获取最新信号")
        print("  GET  /signals         - 获取所有信号")
        print("  POST /analyze         - 触发分析")
        print("\n⚠️  注意：这是简化版本，使用模拟数据")
        print("🔄 系统正在运行中... (按 Ctrl+C 停止)")
        
        # 保持程序运行
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n⏹️  收到停止信号，正在关闭系统...")
        analyzer.running = False
        print("✅ 系统已停止")
        
    except Exception as e:
        print(f"❌ 系统启动失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()