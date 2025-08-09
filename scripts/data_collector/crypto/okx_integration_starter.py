#!/usr/bin/env python3
"""
OKX策略集成的加密货币分析系统启动脚本
与okx_strategy项目完全集成，获取配置、处理符号映射
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
from qlib.contrib.strategy.okx_config_client import create_okx_config_client
from binance_collector import BinanceRun
from binance_dump_bin import DumpBinanceRun
from loguru import logger


class OKXIntegratedAnalysisSystem:
    """与OKX策略完全集成的加密货币分析系统"""
    
    def __init__(
        self,
        okx_api_url: str = "http://localhost:9090",
        data_dir: str = "~/.qlib/okx_binance_data",
        qlib_data_dir: str = "~/.qlib/qlib_data/okx_crypto",
        output_dir: str = "/tmp/okx_crypto_signals",
        websocket_port: int = 8765,
        http_port: int = 8080,
    ):
        """
        初始化OKX集成分析系统
        
        Parameters
        ----------
        okx_api_url: str
            OKX策略项目的API地址
        data_dir: str
            原始数据目录
        qlib_data_dir: str
            qlib格式数据目录
        output_dir: str
            信号输出目录
        websocket_port: int
            WebSocket端口
        http_port: int
            HTTP API端口
        """
        self.okx_api_url = okx_api_url
        self.data_dir = Path(data_dir).expanduser()
        self.qlib_data_dir = Path(qlib_data_dir).expanduser()
        self.output_dir = output_dir
        self.websocket_port = websocket_port
        self.http_port = http_port
        
        # 创建OKX配置客户端
        self.config_client = create_okx_config_client(okx_api_url)
        
        # 初始化组件
        self.analyzer = None
        self.go_interface = None
        self.collector = None
        
        # 配置信息
        self.binance_config = None
        self.qlib_config = None
        self.symbol_mapping = None
        
        # 创建必要目录
        self._create_directories()

    def _create_directories(self):
        """创建必要的目录结构"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "source" / "1d").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "normalize" / "1d").mkdir(parents=True, exist_ok=True)
        self.qlib_data_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"目录结构创建完成: {self.data_dir}")

    def check_integration_status(self) -> bool:
        """检查集成状态"""
        logger.info("检查OKX集成状态...")
        
        status = self.config_client.get_integration_status()
        
        if status["integration_ready"]:
            logger.info("✅ OKX集成检查通过")
            return True
        else:
            logger.error("❌ OKX集成检查失败:")
            for key, value in status.items():
                if isinstance(value, bool) and not value:
                    logger.error(f"  - {key}: {value}")
            return False

    def load_configurations(self) -> bool:
        """从OKX项目加载配置"""
        logger.info("从OKX项目加载配置...")
        
        # 加载Binance配置
        self.binance_config = self.config_client.get_binance_config()
        if not self.binance_config:
            logger.error("无法加载Binance配置")
            return False
        
        # 加载qlib配置
        self.qlib_config = self.config_client.get_qlib_config()
        if not self.qlib_config:
            logger.error("无法加载qlib配置")
            return False
        
        # 加载符号映射
        self.symbol_mapping = self.config_client.get_symbol_mapping()
        if not self.symbol_mapping:
            logger.error("无法加载符号映射")
            return False
        
        logger.info(f"✅ 配置加载完成:")
        logger.info(f"  - Binance测试网: {self.binance_config.get('testnet')}")
        logger.info(f"  - qlib启用: {self.qlib_config.get('enable')}")
        logger.info(f"  - 最小置信度: {self.qlib_config.get('min_confidence')}")
        logger.info(f"  - 符号映射数量: {len(self.symbol_mapping)}")
        
        return True

    def setup_data_collection(self) -> bool:
        """设置数据收集器"""
        logger.info("设置Binance数据收集器...")
        
        data_config = self.config_client.get_data_collection_config()
        interval = data_config.get("interval", "1d")
        
        source_dir = self.data_dir / "source" / interval
        normalize_dir = self.data_dir / "normalize" / interval
        
        try:
            self.collector = BinanceRun(
                source_dir=str(source_dir),
                normalize_dir=str(normalize_dir),
                max_workers=data_config.get("batch_size", 8),
                interval=interval,
            )
            
            logger.info(f"✅ 数据收集器配置完成: {interval} 数据")
            return True
            
        except Exception as e:
            logger.error(f"❌ 数据收集器设置失败: {e}")
            return False

    def collect_historical_data(
        self,
        start_date: str = None,
        end_date: str = None,
        force_update: bool = False,
    ) -> bool:
        """收集历史数据"""
        if not self.collector:
            if not self.setup_data_collection():
                return False
        
        data_config = self.config_client.get_data_collection_config()
        symbols = self.config_client.get_recommended_symbols()
        
        if not start_date:
            # 根据配置决定历史数据范围
            history_days = data_config.get("history_days", 365)
            import datetime
            start_date = (datetime.datetime.now() - datetime.timedelta(days=history_days)).strftime("%Y-%m-%d")
        
        if not end_date:
            end_date = time.strftime("%Y-%m-%d")
        
        logger.info(f"开始收集历史数据: {start_date} 到 {end_date}")
        logger.info(f"收集交易对数量: {len(symbols)}")
        
        try:
            # 下载原始数据
            logger.info("1. 下载原始数据...")
            self.collector.download_data(
                start=start_date,
                end=end_date,
                limit_nums=len(symbols),  # 使用推荐的交易对数量
                delay=0.1,
            )
            
            # 标准化数据
            logger.info("2. 标准化数据...")
            self.collector.normalize_data()
            
            # 转换为qlib格式
            logger.info("3. 转换为qlib格式...")
            dumper = DumpBinanceRun()
            dumper.dump_all(
                csv_path=str(self.data_dir / "normalize" / data_config.get("interval", "1d")),
                qlib_dir=str(self.qlib_data_dir),
                freq="day" if data_config.get("interval", "1d") == "1d" else data_config.get("interval"),
                max_workers=data_config.get("batch_size", 8),
            )
            
            logger.info("✅ 历史数据收集完成")
            
            # 验证数据
            logger.info("4. 验证数据...")
            test_symbols = ','.join(symbols[:5])  # 验证前5个交易对
            dumper.validate_data(
                qlib_dir=str(self.qlib_data_dir),
                symbols=test_symbols
            )
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 历史数据收集失败: {e}")
            return False

    def setup_analyzer(self) -> bool:
        """设置实时分析器"""
        logger.info("设置实时分析器...")
        
        try:
            # 获取更新间隔
            data_config = self.config_client.get_data_collection_config()
            update_interval = data_config.get("update_interval", 30)
            
            self.analyzer = CryptoRealtimeAnalyzer(
                qlib_provider_uri=str(self.qlib_data_dir),
                websocket_port=self.websocket_port,
                update_interval=update_interval,
            )
            
            logger.info("✅ 实时分析器配置完成")
            return True
            
        except Exception as e:
            logger.error(f"❌ 实时分析器设置失败: {e}")
            return False

    def setup_go_interface(self) -> bool:
        """设置Go程序通信接口"""
        logger.info("设置Go程序通信接口...")
        
        try:
            self.go_interface = GoTradingInterface(
                analyzer=self.analyzer,
                http_port=self.http_port,
                output_dir=self.output_dir,
                redis_config={"host": "localhost", "port": 6379, "db": 0},
            )
            
            # 设置符号映射处理
            self._setup_symbol_mapping_processor()
            
            logger.info("✅ Go通信接口配置完成")
            return True
            
        except Exception as e:
            logger.error(f"❌ Go通信接口设置失败: {e}")
            return False

    def _setup_symbol_mapping_processor(self):
        """设置符号映射处理器"""
        # 扩展go_interface以处理符号映射
        original_export = self.go_interface.export_signals_to_files
        
        def enhanced_export(signals):
            # 转换符号格式
            okx_signals = {}
            for binance_symbol, signal_data in signals.items():
                okx_symbol = self.symbol_mapping.get(binance_symbol)
                if okx_symbol:
                    # 复制信号数据并更新符号
                    okx_signal_data = signal_data.copy()
                    okx_signal_data['symbol'] = okx_symbol
                    okx_signal_data['original_symbol'] = binance_symbol
                    okx_signals[okx_symbol] = okx_signal_data
                    
                    logger.debug(f"符号映射: {binance_symbol} -> {okx_symbol}")
            
            # 导出映射后的信号
            if okx_signals:
                original_export(okx_signals)
                logger.info(f"导出了 {len(okx_signals)} 个OKX格式信号")
        
        # 替换导出方法
        self.go_interface.export_signals_to_files = enhanced_export

    def start_analysis_system(self, symbols: List[str] = None) -> bool:
        """启动完整的分析系统"""
        try:
            # 检查集成状态
            if not self.check_integration_status():
                return False
            
            # 加载配置
            if not self.load_configurations():
                return False
            
            # 获取分析交易对
            if symbols is None:
                symbols = self.config_client.get_recommended_symbols()
            
            logger.info(f"启动分析系统，监控 {len(symbols)} 个交易对")
            
            # 检查qlib是否启用
            if not self.qlib_config.get("enable", False):
                logger.warning("qlib集成未启用，请在OKX项目中启用")
                return False
            
            # 设置分析器
            if not self.setup_analyzer():
                return False
            
            # 设置Go通信接口
            if not self.setup_go_interface():
                return False
            
            # 获取客户端集成信息
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
            logger.info("启动实时分析...")
            self.analyzer.start_analysis(symbols)
            
            # 系统运行信息
            self._print_system_info(symbols)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 分析系统启动失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _print_system_info(self, symbols: List[str]):
        """打印系统运行信息"""
        okx_symbols = self.config_client.convert_symbols_for_okx(symbols[:10])
        
        print("\n" + "="*70)
        print("🎉 OKX集成加密货币分析系统启动成功!")
        print("="*70)
        print(f"🔗 OKX策略API: {self.okx_api_url}")
        print(f"📊 数据源: Binance API")
        print(f"💾 数据目录: {self.qlib_data_dir}")
        print(f"📡 HTTP API: http://localhost:{self.http_port}")
        print(f"🔌 WebSocket: ws://localhost:{self.websocket_port}")
        print(f"📁 信号输出: {self.output_dir}")
        print(f"🎯 最小置信度: {self.qlib_config.get('min_confidence')}")
        print(f"⚖️  信号权重: {self.qlib_config.get('signal_weight')}")
        print(f"📈 监控交易对: {len(symbols)}个 (Binance格式)")
        
        print("\n📋 可用API端点:")
        print("  GET  /health              - 健康检查")
        print("  GET  /signals/latest      - 获取最新信号")
        print("  GET  /signals?symbols=... - 获取指定符号信号")
        print("  POST /analyze             - 触发即时分析")
        print("  GET  /symbols             - 获取所有监控的交易对")
        
        print("\n🔄 符号映射示例 (Binance -> OKX):")
        for i, (binance_symbol, okx_symbol) in enumerate(zip(symbols[:5], okx_symbols), 1):
            print(f"  {i:2d}. {binance_symbol:10s} -> {okx_symbol}")
        if len(symbols) > 5:
            print(f"     ... 以及其他 {len(symbols) - 5} 个交易对")
        
        print(f"\n🔄 系统正在运行中... (按 Ctrl+C 停止)")
        print("="*70)

    def stop_system(self):
        """停止分析系统"""
        logger.info("正在停止分析系统...")
        if self.analyzer:
            self.analyzer.stop_analysis()
        logger.info("✅ 系统已停止")


def main():
    parser = argparse.ArgumentParser(description="OKX集成加密货币分析系统")
    parser.add_argument("command", choices=["collect", "analyze", "full"], 
                       help="运行模式: collect(仅收集数据), analyze(仅分析), full(完整系统)")
    parser.add_argument("--okx-api", default="http://localhost:9090", help="OKX策略API地址")
    parser.add_argument("--start-date", default=None, help="数据开始日期")
    parser.add_argument("--end-date", default=None, help="数据结束日期")
    parser.add_argument("--symbols", default=None, help="指定交易对，逗号分隔")
    parser.add_argument("--http-port", type=int, default=8080, help="HTTP API端口")
    parser.add_argument("--websocket-port", type=int, default=8765, help="WebSocket端口")
    parser.add_argument("--data-dir", default="~/.qlib/okx_binance_data", help="数据目录")
    parser.add_argument("--output-dir", default="/tmp/okx_crypto_signals", help="输出目录")
    parser.add_argument("--force-update", action="store_true", help="强制更新数据")
    
    args = parser.parse_args()
    
    # 创建系统实例
    system = OKXIntegratedAnalysisSystem(
        okx_api_url=args.okx_api,
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        websocket_port=args.websocket_port,
        http_port=args.http_port,
    )
    
    try:
        if args.command == "collect":
            # 仅收集数据
            logger.info("🔄 数据收集模式")
            success = system.collect_historical_data(
                start_date=args.start_date,
                end_date=args.end_date,
                force_update=args.force_update,
            )
            if success:
                print("✅ 数据收集完成")
            else:
                print("❌ 数据收集失败")
                
        elif args.command == "analyze":
            # 仅运行分析
            logger.info("🔄 分析模式")
            symbols = None
            if args.symbols:
                symbols = [s.strip().upper() for s in args.symbols.split(",")]
            
            if system.start_analysis_system(symbols):
                # 保持运行
                while True:
                    time.sleep(1)
            else:
                print("❌ 分析系统启动失败")
                
        elif args.command == "full":
            # 完整系统：先收集数据，再启动分析
            logger.info("🔄 完整系统模式")
            
            # 1. 收集数据
            print("🔄 第一步: 收集历史数据...")
            if not system.collect_historical_data(
                start_date=args.start_date,
                end_date=args.end_date,
                force_update=args.force_update,
            ):
                print("❌ 数据收集失败")
                return
            
            # 2. 启动分析系统
            print("🔄 第二步: 启动分析系统...")
            symbols = None
            if args.symbols:
                symbols = [s.strip().upper() for s in args.symbols.split(",")]
            
            if system.start_analysis_system(symbols):
                # 保持主线程运行
                while True:
                    time.sleep(1)
            else:
                print("❌ 分析系统启动失败")
    
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