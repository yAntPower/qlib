#!/usr/bin/env python3
"""
WebSocket服务器 - 实时推送ML策略信号
"""

import asyncio
import websockets
import json
import logging
import time
from datetime import datetime
from typing import Set, Dict, Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class MLWebSocketServer:
    """ML策略WebSocket服务器"""
    
    def __init__(self, analyzer, port=8765):
        """
        初始化WebSocket服务器
        
        Args:
            analyzer: ML分析器实例
            port: WebSocket端口
        """
        self.analyzer = analyzer
        self.port = port
        self.clients: Set[websockets.WebSocketServerProtocol] = set()
        self.last_signals: Dict[str, Any] = {}
        self.signal_check_interval = 300  # 每5分钟检查一次信号，避免重复推送
        
    async def register(self, websocket):
        """注册新客户端"""
        self.clients.add(websocket)
        logger.info(f"新客户端连接: {websocket.remote_address}")
        
        # 发送欢迎消息和当前信号
        await self.send_welcome(websocket)
        
    async def unregister(self, websocket):
        """注销客户端"""
        self.clients.remove(websocket)
        logger.info(f"客户端断开: {websocket.remote_address}")
        
    async def send_welcome(self, websocket):
        """发送欢迎消息和初始信号"""
        welcome_msg = {
            "type": "welcome",
            "timestamp": datetime.now().isoformat(),
            "message": "Connected to ML Strategy WebSocket Server",
            "symbols": self.analyzer.symbols
        }
        await websocket.send(json.dumps(welcome_msg))
        
        # 发送当前信号
        signals = self.analyzer.get_all_signals()
        if signals:
            signal_msg = {
                "type": "signals",
                "timestamp": datetime.now().isoformat(),
                "data": {}
            }
            
            for symbol, signal in signals.items():
                # 只发送置信度超过阈值的信号
                if signal and signal.get('confidence', 0) > 0.30:
                    signal_msg["data"][symbol] = signal
                    
            if signal_msg["data"]:
                await websocket.send(json.dumps(signal_msg))
                logger.info(f"发送初始信号给新客户端: {len(signal_msg['data'])} 个信号")
    
    async def broadcast(self, message: Dict[str, Any]):
        """广播消息给所有客户端"""
        if self.clients:
            message_str = json.dumps(message)
            # 创建所有发送任务
            tasks = [asyncio.create_task(client.send(message_str)) 
                    for client in self.clients]
            
            # 等待所有发送完成，忽略失败的连接
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 清理失败的连接
            for client, result in zip(list(self.clients), results):
                if isinstance(result, Exception):
                    logger.warning(f"发送失败，移除客户端: {result}")
                    self.clients.discard(client)
                    
            logger.info(f"广播消息给 {len(self.clients)} 个客户端")
    
    async def check_and_broadcast_signals(self):
        """定期检查并广播新信号"""
        while True:
            try:
                # 获取最新信号
                signals = self.analyzer.get_all_signals()
                
                # 检查是否有新信号或信号变化
                new_signals = {}
                for symbol, signal in signals.items():
                    if not signal:
                        continue
                        
                    # 检查置信度阈值
                    if signal.get('confidence', 0) <= 0.30:
                        continue
                    
                    # 检查信号是否变化
                    last_signal = self.last_signals.get(symbol, {})
                    
                    # 比较关键字段
                    if (last_signal.get('recommendation') != signal.get('recommendation') or
                        abs(last_signal.get('confidence', 0) - signal.get('confidence', 0)) > 0.05):
                        new_signals[symbol] = signal
                        logger.info(f"检测到新信号: {symbol} - {signal['recommendation']} "
                                  f"(置信度: {signal['confidence']*100:.1f}%)")
                
                # 如果有新信号，广播给所有客户端
                if new_signals:
                    message = {
                        "type": "signals_update",
                        "timestamp": datetime.now().isoformat(),
                        "data": new_signals
                    }
                    await self.broadcast(message)
                    
                    # 更新最后信号记录
                    for symbol, signal in new_signals.items():
                        self.last_signals[symbol] = signal
                        
                    # 触发纸上交易（如果方法存在）
                    if hasattr(self.analyzer, 'execute_paper_trade'):
                        for symbol, signal in new_signals.items():
                            if signal.get('recommendation') in ['BUY', 'SELL']:
                                trade_result = self.analyzer.execute_paper_trade(
                                    symbol, 
                                    signal['recommendation'],
                                    signal.get('price', 0),
                                    signal.get('confidence', 0)
                                )
                                
                                # 广播交易执行消息
                                trade_msg = {
                                    "type": "paper_trade",
                                    "timestamp": datetime.now().isoformat(),
                                    "data": trade_result
                                }
                                await self.broadcast(trade_msg)
                
            except Exception as e:
                logger.error(f"检查信号时出错: {e}")
                
            # 等待下一次检查
            await asyncio.sleep(self.signal_check_interval)
    
    async def handle_client(self, websocket):
        """处理客户端连接"""
        await self.register(websocket)
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    
                    # 处理客户端请求
                    if data.get("action") == "get_signals":
                        # 立即返回当前信号
                        signals = self.analyzer.get_all_signals()
                        response = {
                            "type": "signals",
                            "timestamp": datetime.now().isoformat(),
                            "data": signals
                        }
                        await websocket.send(json.dumps(response))
                        
                    elif data.get("action") == "subscribe":
                        # 订阅特定符号（可选功能）
                        symbols = data.get("symbols", [])
                        response = {
                            "type": "subscribed",
                            "symbols": symbols,
                            "timestamp": datetime.now().isoformat()
                        }
                        await websocket.send(json.dumps(response))
                        
                    elif data.get("action") == "ping":
                        # 心跳响应
                        pong = {
                            "type": "pong",
                            "timestamp": datetime.now().isoformat()
                        }
                        await websocket.send(json.dumps(pong))
                        
                except json.JSONDecodeError:
                    error_msg = {
                        "type": "error",
                        "message": "Invalid JSON format"
                    }
                    await websocket.send(json.dumps(error_msg))
                    
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            await self.unregister(websocket)
    
    async def broadcast_signals(self, signals):
        """广播信号给所有连接的客户端"""
        if not self.clients:
            return
            
        message = {
            "type": "signals_update",
            "signals": signals,
            "timestamp": datetime.now().isoformat()
        }
        
        # 向所有客户端发送信号
        disconnected = set()
        for client in self.clients:
            try:
                await client.send(json.dumps(message))
            except:
                disconnected.add(client)
        
        # 移除断开的客户端
        for client in disconnected:
            self.clients.discard(client)
        
        logger.info(f"广播信号给 {len(self.clients)} 个客户端")
    
    async def start(self):
        """启动WebSocket服务器"""
        logger.info(f"启动WebSocket服务器在端口 {self.port}")
        
        # 启动信号检查任务
        asyncio.create_task(self.check_and_broadcast_signals())
        
        # 启动WebSocket服务器
        async with websockets.serve(self.handle_client, "0.0.0.0", self.port):
            logger.info(f"WebSocket服务器运行中: ws://localhost:{self.port}")
            await asyncio.Future()  # 永远运行


def start_websocket_server(analyzer, port=8765):
    """启动WebSocket服务器的辅助函数"""
    server = MLWebSocketServer(analyzer, port)
    asyncio.run(server.start())


if __name__ == "__main__":
    # 测试模式
    print("WebSocket服务器模块 - 需要与ML策略一起运行")