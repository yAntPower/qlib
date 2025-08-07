#!/usr/bin/env python3
"""
Binance数据加密货币分析系统启动脚本
集成Binance数据收集、实时分析和Go程序通信
"""

import sys
import time
import threading
import argparse
from pathlib import Path
from typing import List, Dict, Optional

# 添加qlib路径
CUR_DIR = Path(__file__).resolve().parent
sys.path.append(str(CUR_DIR.parent.parent.parent))

from qlib.contrib.strategy.crypto_realtime_analyzer import CryptoRealtimeAnalyzer
from qlib.contrib.strategy.go_communication import GoTradingInterface
from binance_collector import BinanceRun
from binance_dump_bin import DumpBinanceRun
from loguru import logger


class BinanceCryptoAnalysisSystem:
    """Binance加密货币分析系统"""
    
    def __init__(
        self,
        data_dir: str = "~/.qlib/binance_data",
        qlib_data_dir: str = "~/.qlib/qlib_data/binance_crypto",
        output_dir: str = "/tmp/binance_crypto_signals",
        websocket_port: int = 8765,
        http_port: int = 8080,
        update_interval: int = 30,
        redis_config: Optional[Dict] = None,
    ):
        """
        初始化Binance分析系统
        
        Parameters
        ----------
        data_dir: str
            原始数据和标准化数据目录
        qlib_data_dir: str
            qlib格式数据目录
        output_dir: str
            信号输出目录
        websocket_port: int
            WebSocket端口
        http_port: int
            HTTP API端口
        update_interval: int
            分析更新间隔（秒）
        redis_config: dict
            Redis配置
        """
        self.data_dir = Path(data_dir).expanduser()
        self.qlib_data_dir = Path(qlib_data_dir).expanduser()
        self.output_dir = output_dir
        self.websocket_port = websocket_port
        self.http_port = http_port
        self.update_interval = update_interval
        self.redis_config = redis_config
        
        # 创建必要目录
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "source" / "1d").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "normalize" / "1d").mkdir(parents=True, exist_ok=True)
        self.qlib_data_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化组件
        self.collector = None
        self.analyzer = None
        self.go_interface = None

    def setup_data_collection(self, interval: str = "1d"):
        """设置数据收集器"""
        logger.info("设置Binance数据收集器...")
        
        source_dir = self.data_dir / "source" / interval
        normalize_dir = self.data_dir / "normalize" / interval
        
        self.collector = BinanceRun(
            source_dir=str(source_dir),
            normalize_dir=str(normalize_dir),
            max_workers=4,
            interval=interval,
        )
        
        logger.info(f"数据收集器配置完成: {source_dir} -> {normalize_dir}")

    def collect_data(
        self,
        start_date: str = "2023-01-01",
        end_date: str = None,
        interval: str = "1d",
        limit_nums: int = None,
        force_update: bool = False,
    ):
        """收集Binance数据"""
        if not end_date:
            end_date = time.strftime("%Y-%m-%d")
        
        logger.info(f"开始收集Binance数据: {start_date} 到 {end_date}, 间隔: {interval}")
        
        # 设置收集器
        self.setup_data_collection(interval)
        
        try:
            # 下载原始数据
            logger.info("1. 下载原始数据...")
            self.collector.download_data(
                start=start_date,
                end=end_date,
                limit_nums=limit_nums,
                delay=0.1,  # Binance限制较松，可以快一些
            )
            
            # 标准化数据
            logger.info("2. 标准化数据...")
            self.collector.normalize_data()
            
            # 转换为qlib格式
            logger.info("3. 转换为qlib格式...")
            dumper = DumpBinanceRun()
            dumper.dump_all(
                csv_path=str(self.data_dir / "normalize" / interval),
                qlib_dir=str(self.qlib_data_dir),
                freq="day" if interval == "1d" else interval,
                max_workers=8,
            )
            
            logger.info("✅ 数据收集完成")
            
            # 验证数据
            logger.info("4. 验证数据...")
            dumper.validate_data(
                qlib_dir=str(self.qlib_data_dir),
                symbols="BTCUSDT,ETHUSDT,ADAUSDT,DOTUSDT,BNBUSDT"
            )
            
        except Exception as e:
            logger.error(f"❌ 数据收集失败: {e}")
            raise

    def setup_analyzer(self):
        """设置实时分析器"""
        logger.info("设置实时分析器...")
        
        # 创建分析器
        self.analyzer = CryptoRealtimeAnalyzer(
            qlib_provider_uri=str(self.qlib_data_dir),
            websocket_port=self.websocket_port,
            update_interval=self.update_interval,
            redis_config=self.redis_config,
        )
        
        logger.info("✅ 实时分析器配置完成")

    def setup_go_interface(self):
        """设置Go程序通信接口"""
        logger.info("设置Go程序通信接口...")
        
        self.go_interface = GoTradingInterface(
            analyzer=self.analyzer,
            http_port=self.http_port,
            output_dir=self.output_dir,
            redis_config=self.redis_config,
        )
        
        logger.info("✅ Go通信接口配置完成")

    def get_active_symbols(self, top_n: int = 50) -> List[str]:
        """获取活跃的交易对列表"""
        try:
            # 使用Binance收集器获取交易对
            temp_collector = BinanceRun(source_dir="/tmp", interval="1d")
            temp_collector.setup_data_collection("1d")
            
            collector_instance = temp_collector.collector_class()
            symbols = collector_instance.get_crypto_symbols()
            
            # 选择前N个最活跃的交易对
            # 这里可以加入更复杂的筛选逻辑（如成交量、市值等）
            popular_symbols = [
                'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'DOTUSDT',
                'XRPUSDT', 'SOLUSDT', 'DOGEUSDT', 'AVAXUSDT', 'MATICUSDT',
                'LINKUSDT', 'ATOMUSDT', 'LTCUSDT', 'UNIUSDT', 'ALGOUSDT',
                'VETUSDT', 'XLMUSDT', 'FILUSDT', 'TRXUSDT', 'ETCUSDT',
            ]
            
            # 优先使用热门交易对，然后补充其他
            result_symbols = []
            for symbol in popular_symbols:
                if symbol in symbols and len(result_symbols) < top_n:
                    result_symbols.append(symbol)
            
            # 如果热门交易对不够，从其他交易对中补充
            for symbol in symbols:
                if symbol not in result_symbols and len(result_symbols) < top_n:
                    result_symbols.append(symbol)
            
            logger.info(f"选择了 {len(result_symbols)} 个活跃交易对进行分析")
            return result_symbols
            
        except Exception as e:
            logger.error(f"获取交易对列表失败: {e}")
            # 返回默认列表
            return ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'DOTUSDT']

    def start_analysis_system(self, symbols: List[str] = None):
        """启动完整的分析系统"""
        try:
            # 获取分析交易对
            if symbols is None:
                symbols = self.get_active_symbols()
            
            logger.info(f"启动分析系统，监控 {len(symbols)} 个交易对")
            
            # 设置分析器
            self.setup_analyzer()
            
            # 设置Go通信接口
            self.setup_go_interface()
            
            # 获取客户端集成信息
            logger.info("获取客户端集成信息...")
            client_info = self.go_interface.get_client_integration_info()
            logger.info(f"客户端集成: {client_info['integration_note']}")
            
            # 启动HTTP服务器
            logger.info(f"启动HTTP API服务器 (端口 {self.http_port})...")
            self.go_interface.start_http_server_thread()
            
            # 启动WebSocket服务器
            logger.info(f"启动WebSocket服务器 (端口 {self.websocket_port})...")
            ws_thread = threading.Thread(
                target=self.analyzer.start_websocket_server,
                daemon=True
            )
            ws_thread.start()
            
            # 启动实时分析
            logger.info(f"启动实时分析...")
            self.analyzer.start_analysis(symbols)
            
            # 系统运行信息
            self._print_system_info(symbols, go_client_path)
            
            return True
            
        except Exception as e:
            logger.error(f"启动分析系统失败: {e}")
            return False

    def _print_system_info(self, symbols: List[str], go_client_path: Path):
        """打印系统运行信息"""
        print("\n" + "="*60)
        print("🎉 Binance加密货币分析系统启动成功!")
        print("="*60)
        print(f"📊 数据源: Binance API")
        print(f"💾 数据目录: {self.qlib_data_dir}")
        print(f"📡 HTTP API: http://localhost:{self.http_port}")
        print(f"🔌 WebSocket: ws://localhost:{self.websocket_port}")
        print(f"📁 信号输出: {self.output_dir}")
        print(f"🐹 Go客户端: {go_client_path}")
        print(f"🔄 更新间隔: {self.update_interval}秒")
        print(f"📈 监控交易对: {len(symbols)}个")
        
        print("\n📋 可用API端点:")
        print("  GET  /health              - 健康检查")
        print("  GET  /signals/latest      - 获取最新信号")
        print("  GET  /signals?symbols=... - 获取指定符号信号")
        print("  POST /analyze             - 触发即时分析")
        print("  GET  /symbols             - 获取所有监控的交易对")
        
        print("\n🎯 监控的交易对:")
        for i, symbol in enumerate(symbols[:10], 1):  # 只显示前10个
            print(f"  {i:2d}. {symbol}")
        if len(symbols) > 10:
            print(f"     ... 以及其他 {len(symbols) - 10} 个交易对")
        
        print(f"\n🔄 系统正在运行中... (按 Ctrl+C 停止)")
        print("="*60)

    def stop_system(self):
        """停止分析系统"""
        logger.info("正在停止分析系统...")
        if self.analyzer:
            self.analyzer.stop_analysis()
        logger.info("✅ 系统已停止")

    def run_data_update_loop(self, interval_hours: int = 6):
        """运行数据更新循环"""
        logger.info(f"启动数据更新循环，每 {interval_hours} 小时更新一次")
        
        while True:
            try:
                # 获取最新数据
                end_date = time.strftime("%Y-%m-%d")
                start_date = time.strftime(
                    "%Y-%m-%d", 
                    time.gmtime(time.time() - 7 * 24 * 60 * 60)  # 过去7天
                )
                
                logger.info(f"更新数据: {start_date} 到 {end_date}")
                self.collect_data(
                    start_date=start_date,
                    end_date=end_date,
                    interval="1d",
                    limit_nums=50,  # 只更新主要交易对
                    force_update=True,
                )
                
            except Exception as e:
                logger.error(f"数据更新失败: {e}")
            
            # 等待下次更新
            time.sleep(interval_hours * 3600)


def main():
    parser = argparse.ArgumentParser(description="Binance加密货币分析系统")
    parser.add_argument("command", choices=["collect", "analyze", "full"], 
                       help="运行模式: collect(仅收集数据), analyze(仅分析), full(完整系统)")
    parser.add_argument("--start-date", default="2023-01-01", help="数据开始日期")
    parser.add_argument("--end-date", default=None, help="数据结束日期")
    parser.add_argument("--interval", default="1d", choices=["1m", "5m", "15m", "1h", "4h", "1d"], 
                       help="数据时间间隔")
    parser.add_argument("--symbols", default=None, help="指定交易对，逗号分隔")
    parser.add_argument("--limit-nums", type=int, default=None, help="限制交易对数量")
    parser.add_argument("--update-interval", type=int, default=30, help="分析更新间隔(秒)")
    parser.add_argument("--http-port", type=int, default=8080, help="HTTP API端口")
    parser.add_argument("--websocket-port", type=int, default=8765, help="WebSocket端口")
    parser.add_argument("--data-dir", default="~/.qlib/binance_data", help="数据目录")
    parser.add_argument("--output-dir", default="/tmp/binance_crypto_signals", help="输出目录")
    parser.add_argument("--redis-host", default="localhost", help="Redis主机")
    parser.add_argument("--redis-port", type=int, default=6379, help="Redis端口")
    parser.add_argument("--no-redis", action="store_true", help="禁用Redis")
    
    args = parser.parse_args()
    
    # Redis配置
    redis_config = None
    if not args.no_redis:
        redis_config = {
            "host": args.redis_host,
            "port": args.redis_port,
            "db": 0
        }
    
    # 创建系统实例
    system = BinanceCryptoAnalysisSystem(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        websocket_port=args.websocket_port,
        http_port=args.http_port,
        update_interval=args.update_interval,
        redis_config=redis_config,
    )
    
    try:
        if args.command == "collect":
            # 仅收集数据
            system.collect_data(
                start_date=args.start_date,
                end_date=args.end_date,
                interval=args.interval,
                limit_nums=args.limit_nums,
            )
            
        elif args.command == "analyze":
            # 仅运行分析
            symbols = None
            if args.symbols:
                symbols = [s.strip().upper() for s in args.symbols.split(",")]
            
            if system.start_analysis_system(symbols):
                # 保持运行
                while True:
                    time.sleep(1)
                    
        elif args.command == "full":
            # 完整系统：先收集数据，再启动分析
            
            # 1. 收集数据
            print("🔄 第一步: 收集历史数据...")
            system.collect_data(
                start_date=args.start_date,
                end_date=args.end_date,
                interval=args.interval,
                limit_nums=args.limit_nums,
            )
            
            # 2. 启动分析系统
            print("🔄 第二步: 启动分析系统...")
            symbols = None
            if args.symbols:
                symbols = [s.strip().upper() for s in args.symbols.split(",")]
            
            if system.start_analysis_system(symbols):
                # 启动数据更新循环
                update_thread = threading.Thread(
                    target=system.run_data_update_loop,
                    args=(6,),  # 每6小时更新一次
                    daemon=True
                )
                update_thread.start()
                
                # 保持主线程运行
                while True:
                    time.sleep(1)
    
    except KeyboardInterrupt:
        print("\n⏹️  收到停止信号...")
        system.stop_system()
        print("✅ 系统已停止")
        
    except Exception as e:
        logger.error(f"❌ 系统运行失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()