#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Go程序通信接口
提供多种通信方式：WebSocket、HTTP API、Redis、文件等
"""

import json
import time
import asyncio
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from pathlib import Path
import http.server
import socketserver
from urllib.parse import urlparse, parse_qs
import queue

from loguru import logger


class GoTradingInterface:
    """与Go交易程序的通信接口"""
    
    def __init__(
        self,
        analyzer,
        http_port: int = 8080,
        output_dir: str = "/tmp/qlib_signals",
        redis_config: Optional[Dict] = None,
        webhook_url: Optional[str] = None,
    ):
        """
        初始化Go通信接口
        
        Parameters
        ----------
        analyzer: CryptoRealtimeAnalyzer
            实时分析器实例
        http_port: int
            HTTP API端口
        output_dir: str
            信号输出目录
        redis_config: dict
            Redis配置
        webhook_url: str
            Webhook URL for notifications
        """
        self.analyzer = analyzer
        self.http_port = http_port
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.redis_config = redis_config
        self.webhook_url = webhook_url
        
        # 创建信号历史队列
        self.signal_history = queue.Queue(maxsize=1000)
        
        # 初始化Redis
        self.redis_client = None
        if redis_config:
            self._init_redis()
        
        logger.info("Go trading interface initialized")

    def _init_redis(self):
        """初始化Redis连接"""
        try:
            import redis
            self.redis_client = redis.Redis(**self.redis_config)
            self.redis_client.ping()
            logger.info("Redis connected for Go communication")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")

    def start_http_server(self):
        """启动HTTP API服务器"""
        handler = self._create_http_handler()
        
        with socketserver.TCPServer(("", self.http_port), handler) as httpd:
            logger.info(f"HTTP API server started on port {self.http_port}")
            httpd.serve_forever()

    def _create_http_handler(self):
        """创建HTTP请求处理器"""
        analyzer = self.analyzer
        interface = self
        
        class APIHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                parsed_path = urlparse(self.path)
                path = parsed_path.path
                query_params = parse_qs(parsed_path.query)
                
                if path == "/signals":
                    self._handle_get_signals(query_params)
                elif path == "/signals/latest":
                    self._handle_get_latest_signals()
                elif path == "/signals/history":
                    self._handle_get_signal_history(query_params)
                elif path == "/health":
                    self._handle_health_check()
                elif path == "/symbols":
                    self._handle_get_symbols()
                else:
                    self._send_error(404, "Not Found")

            def do_POST(self):
                parsed_path = urlparse(self.path)
                path = parsed_path.path
                
                if path == "/analyze":
                    self._handle_analyze_request()
                elif path == "/webhook/register":
                    self._handle_webhook_register()
                else:
                    self._send_error(404, "Not Found")

            def _handle_get_signals(self, query_params):
                """获取指定符号的交易信号"""
                try:
                    symbols = query_params.get('symbols', [''])
                    if symbols and symbols[0]:
                        symbols = symbols[0].split(',')
                        signals = analyzer.get_crypto_signals(symbols)
                    else:
                        signals = analyzer.get_latest_signals()
                    
                    self._send_json_response(200, {
                        "status": "success",
                        "timestamp": datetime.now().isoformat(),
                        "data": signals
                    })
                except Exception as e:
                    self._send_error(500, str(e))

            def _handle_get_latest_signals(self):
                """获取最新信号"""
                try:
                    signals = analyzer.get_latest_signals()
                    self._send_json_response(200, {
                        "status": "success",
                        "timestamp": datetime.now().isoformat(),
                        "data": signals
                    })
                except Exception as e:
                    self._send_error(500, str(e))

            def _handle_get_signal_history(self, query_params):
                """获取信号历史"""
                try:
                    limit = int(query_params.get('limit', ['100'])[0])
                    history = []
                    
                    # 从队列中获取历史记录
                    temp_queue = queue.Queue()
                    while not interface.signal_history.empty() and len(history) < limit:
                        item = interface.signal_history.get()
                        history.append(item)
                        temp_queue.put(item)
                    
                    # 将项目放回队列
                    while not temp_queue.empty():
                        interface.signal_history.put(temp_queue.get())
                    
                    self._send_json_response(200, {
                        "status": "success",
                        "count": len(history),
                        "data": history
                    })
                except Exception as e:
                    self._send_error(500, str(e))

            def _handle_health_check(self):
                """健康检查"""
                self._send_json_response(200, {
                    "status": "healthy",
                    "timestamp": datetime.now().isoformat(),
                    "analyzer_running": analyzer.is_running,
                })

            def _handle_get_symbols(self):
                """获取支持的交易对"""
                signals = analyzer.get_latest_signals()
                symbols = list(signals.keys())
                
                self._send_json_response(200, {
                    "status": "success",
                    "symbols": symbols,
                    "count": len(symbols)
                })

            def _handle_analyze_request(self):
                """处理分析请求"""
                try:
                    content_length = int(self.headers['Content-Length'])
                    post_data = self.rfile.read(content_length)
                    request_data = json.loads(post_data)
                    
                    symbols = request_data.get('symbols', [])
                    if not symbols:
                        self._send_error(400, "No symbols provided")
                        return
                    
                    signals = analyzer.get_crypto_signals(symbols)
                    
                    self._send_json_response(200, {
                        "status": "success",
                        "timestamp": datetime.now().isoformat(),
                        "data": signals
                    })
                except Exception as e:
                    self._send_error(500, str(e))

            def _handle_webhook_register(self):
                """注册webhook"""
                try:
                    content_length = int(self.headers['Content-Length'])
                    post_data = self.rfile.read(content_length)
                    request_data = json.loads(post_data)
                    
                    webhook_url = request_data.get('url')
                    if webhook_url:
                        interface.webhook_url = webhook_url
                        logger.info(f"Webhook registered: {webhook_url}")
                        
                        self._send_json_response(200, {
                            "status": "success",
                            "message": "Webhook registered successfully"
                        })
                    else:
                        self._send_error(400, "No webhook URL provided")
                        
                except Exception as e:
                    self._send_error(500, str(e))

            def _send_json_response(self, status_code, data):
                """发送JSON响应"""
                self.send_response(status_code)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(data, indent=2).encode('utf-8'))

            def _send_error(self, status_code, message):
                """发送错误响应"""
                self._send_json_response(status_code, {
                    "status": "error",
                    "message": message,
                    "timestamp": datetime.now().isoformat()
                })

            def log_message(self, format, *args):
                """自定义日志格式"""
                logger.info(f"HTTP {format % args}")

        return APIHandler

    def export_signals_to_files(self, signals: Dict):
        """导出信号到文件供Go程序读取"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # JSON格式
            json_file = self.output_dir / f"signals_{timestamp}.json"
            with open(json_file, 'w') as f:
                json.dump(signals, f, indent=2)
            
            # 创建最新信号的符号链接
            latest_file = self.output_dir / "latest_signals.json"
            if latest_file.exists():
                latest_file.unlink()
            latest_file.symlink_to(json_file.name)
            
            # CSV格式（便于Go程序解析）
            csv_file = self.output_dir / f"signals_{timestamp}.csv"
            self._export_signals_to_csv(signals, csv_file)
            
            # 创建最新CSV的符号链接
            latest_csv = self.output_dir / "latest_signals.csv"
            if latest_csv.exists():
                latest_csv.unlink()
            latest_csv.symlink_to(csv_file.name)
            
            # 创建Go格式的结构化文件
            go_file = self.output_dir / f"signals_{timestamp}.go.json"
            self._export_for_go_struct(signals, go_file)
            
            logger.info(f"Signals exported to {self.output_dir}")
            
        except Exception as e:
            logger.error(f"Failed to export signals: {e}")

    def _export_signals_to_csv(self, signals: Dict, filepath: Path):
        """导出信号到CSV格式"""
        import pandas as pd
        
        data = []
        for symbol, signal_data in signals.items():
            row = {
                'symbol': symbol,
                'timestamp': signal_data.get('timestamp', ''),
                'price': signal_data.get('price', 0),
                'volume': signal_data.get('volume', 0),
                'recommendation': signal_data.get('recommendation', 'HOLD'),
                'confidence': signal_data.get('confidence', 0.0),
            }
            
            # 添加技术指标
            tech_signals = signal_data.get('technical_signals', {})
            for key, value in tech_signals.items():
                row[f'tech_{key}'] = value
            
            # 添加ML预测
            ml_pred = signal_data.get('ml_prediction')
            if ml_pred:
                row['ml_prediction'] = ml_pred.get('prediction', 0)
                row['ml_confidence'] = ml_pred.get('confidence', 0)
            
            data.append(row)
        
        df = pd.DataFrame(data)
        df.to_csv(filepath, index=False)

    def _export_for_go_struct(self, signals: Dict, filepath: Path):
        """导出Go结构体友好的格式"""
        go_signals = {
            "timestamp": datetime.now().isoformat(),
            "signals": []
        }
        
        for symbol, signal_data in signals.items():
            go_signal = {
                "symbol": symbol,
                "timestamp": signal_data.get('timestamp', ''),
                "price": float(signal_data.get('price', 0)),
                "volume": float(signal_data.get('volume', 0)),
                "recommendation": signal_data.get('recommendation', 'HOLD'),
                "confidence": float(signal_data.get('confidence', 0.0)),
                "technical_indicators": signal_data.get('technical_signals', {}),
                "ml_prediction": signal_data.get('ml_prediction', {}),
            }
            go_signals["signals"].append(go_signal)
        
        with open(filepath, 'w') as f:
            json.dump(go_signals, f, indent=2)

    def publish_to_redis_queue(self, channel: str, signals: Dict):
        """发布信号到Redis队列"""
        if not self.redis_client:
            return
        
        try:
            message = {
                "timestamp": datetime.now().isoformat(),
                "signals": signals,
                "source": "qlib_analyzer"
            }
            
            # 发布到频道
            self.redis_client.publish(channel, json.dumps(message))
            
            # 也推送到列表（队列）
            self.redis_client.lpush(f"{channel}_queue", json.dumps(message))
            
            # 保持队列大小限制
            self.redis_client.ltrim(f"{channel}_queue", 0, 999)
            
            logger.debug(f"Published signals to Redis channel: {channel}")
            
        except Exception as e:
            logger.error(f"Redis publish failed: {e}")

    def send_webhook_notification(self, signals: Dict):
        """发送Webhook通知"""
        if not self.webhook_url:
            return
        
        try:
            import requests
            
            payload = {
                "timestamp": datetime.now().isoformat(),
                "event": "signals_updated",
                "data": signals,
                "source": "qlib_crypto_analyzer"
            }
            
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=10,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                logger.debug("Webhook notification sent successfully")
            else:
                logger.warning(f"Webhook returned status {response.status_code}")
                
        except Exception as e:
            logger.error(f"Webhook notification failed: {e}")

    def process_signals_update(self, signals: Dict):
        """处理信号更新（统一入口）"""
        try:
            # 添加到历史队列
            signal_record = {
                "timestamp": datetime.now().isoformat(),
                "signals": signals
            }
            
            try:
                self.signal_history.put_nowait(signal_record)
            except queue.Full:
                # 如果队列满了，移除最老的记录
                try:
                    self.signal_history.get_nowait()
                    self.signal_history.put_nowait(signal_record)
                except queue.Empty:
                    pass
            
            # 导出到文件
            self.export_signals_to_files(signals)
            
            # 发布到Redis
            self.publish_to_redis_queue("crypto_trading_signals", signals)
            
            # 发送Webhook通知
            self.send_webhook_notification(signals)
            
            logger.info(f"Processed signal update for {len(signals)} symbols")
            
        except Exception as e:
            logger.error(f"Failed to process signals update: {e}")

    def start_http_server_thread(self):
        """在独立线程中启动HTTP服务器"""
        server_thread = threading.Thread(
            target=self.start_http_server,
            daemon=True
        )
        server_thread.start()
        logger.info(f"HTTP server thread started on port {self.http_port}")
        return server_thread

    def get_client_integration_info(self):
        """获取客户端集成信息"""
        return {
            "http_api_base": f"http://localhost:{self.http_port}",
            "websocket_url": f"ws://localhost:8765",
            "output_directory": str(self.output_dir),
            "supported_endpoints": [
                "GET /health - 健康检查", 
                "GET /signals/latest - 获取最新信号",
                "GET /signals?symbols=X,Y - 获取指定符号信号",
                "POST /analyze - 触发分析"
            ],
            "integration_note": "Go客户端代码已移至专门的okx_strategy项目中，请参考该项目的文档"
        }


# 使用示例
if __name__ == "__main__":
    from crypto_realtime_analyzer import CryptoRealtimeAnalyzer
    
    # 创建分析器
    analyzer = CryptoRealtimeAnalyzer(
        qlib_provider_uri="~/.qlib/qlib_data/crypto_data"
    )
    
    # 创建Go通信接口
    go_interface = GoTradingInterface(
        analyzer=analyzer,
        http_port=8080,
        output_dir="/tmp/qlib_crypto_signals",
        redis_config={
            "host": "localhost",
            "port": 6379,
            "db": 0
        }
    )
    
    # 启动HTTP服务器
    go_interface.start_http_server_thread()
    
    # 获取客户端集成信息
    client_info = go_interface.get_client_integration_info()
    
    print("Go communication interface is running...")
    print(f"HTTP API: {client_info['http_api_base']}")
    print(f"WebSocket: {client_info['websocket_url']}")
    print(f"Signals output: {client_info['output_directory']}")
    print(f"Note: {client_info['integration_note']}")