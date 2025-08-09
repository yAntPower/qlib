#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
OKX项目配置客户端
从okx_strategy项目获取Binance和qlib配置信息
"""

import json
import requests
import time
from typing import Dict, List, Optional, Tuple
from loguru import logger


class OKXConfigClient:
    """OKX配置客户端，用于获取okx_strategy项目的配置"""
    
    def __init__(
        self,
        okx_api_url: str = "http://localhost:9090",  # okx_strategy API地址
        timeout: int = 10,
        max_retries: int = 3,
    ):
        """
        初始化OKX配置客户端
        
        Parameters
        ----------
        okx_api_url: str
            OKX策略项目的API地址
        timeout: int
            请求超时时间
        max_retries: int
            最大重试次数
        """
        self.okx_api_url = okx_api_url.rstrip('/')
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        
        logger.info(f"OKX配置客户端初始化: {okx_api_url}")

    def _make_request(self, endpoint: str, method: str = "GET", data: Optional[Dict] = None) -> Optional[Dict]:
        """发送HTTP请求的通用方法"""
        url = f"{self.okx_api_url}/api/v1{endpoint}"
        
        for attempt in range(self.max_retries):
            try:
                if method.upper() == "GET":
                    response = self.session.get(url, timeout=self.timeout)
                elif method.upper() == "POST":
                    response = self.session.post(url, json=data, timeout=self.timeout)
                elif method.upper() == "PUT":
                    response = self.session.put(url, json=data, timeout=self.timeout)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                
                response.raise_for_status()
                result = response.json()
                
                if result.get("success"):
                    return result.get("data")
                else:
                    logger.error(f"API请求失败: {result.get('error', 'Unknown error')}")
                    return None
                    
            except requests.exceptions.RequestException as e:
                logger.warning(f"请求失败 (尝试 {attempt + 1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)  # 指数退避
                else:
                    logger.error(f"所有重试均失败: {e}")
                    return None
                    
        return None

    def get_binance_config(self) -> Optional[Dict]:
        """获取Binance配置"""
        logger.info("获取Binance配置...")
        config = self._make_request("/config/binance")
        
        if config:
            logger.info(f"获取到Binance配置: 测试网={config.get('testnet')}, "
                       f"交易对数量={len(config.get('symbols', []))}")
            return config
        else:
            logger.error("无法获取Binance配置")
            return None

    def get_qlib_config(self) -> Optional[Dict]:
        """获取qlib集成配置"""
        logger.info("获取qlib集成配置...")
        config = self._make_request("/config/qlib")
        
        if config:
            logger.info(f"获取到qlib配置: 启用={config.get('enable')}, "
                       f"最小置信度={config.get('min_confidence')}")
            return config
        else:
            logger.error("无法获取qlib配置")
            return None

    def get_symbol_mapping(self) -> Optional[Dict[str, str]]:
        """获取交易对符号映射 (Binance -> OKX)"""
        logger.info("获取交易对符号映射...")
        mapping = self._make_request("/config/symbol-mapping")
        
        if mapping:
            logger.info(f"获取到 {len(mapping)} 个交易对映射")
            return mapping
        else:
            logger.error("无法获取交易对映射")
            return None

    def get_recommended_symbols(self) -> List[str]:
        """获取推荐的Binance交易对列表"""
        binance_config = self.get_binance_config()
        if binance_config and "symbols" in binance_config:
            symbols = binance_config["symbols"]
            logger.info(f"获取到 {len(symbols)} 个推荐交易对")
            return symbols
        else:
            # 返回默认列表
            default_symbols = [
                "BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "DOTUSDT",
                "XRPUSDT", "SOLUSDT", "DOGEUSDT", "AVAXUSDT", "MATICUSDT"
            ]
            logger.warning(f"使用默认交易对列表: {len(default_symbols)} 个")
            return default_symbols

    def get_data_collection_config(self) -> Dict:
        """获取数据收集配置"""
        binance_config = self.get_binance_config()
        if binance_config and "data_config" in binance_config:
            data_config = binance_config["data_config"]
            logger.info(f"获取到数据收集配置: 间隔={data_config.get('interval')}, "
                       f"历史天数={data_config.get('history_days')}")
            return data_config
        else:
            # 返回默认配置
            default_config = {
                "interval": "1d",
                "history_days": 365,
                "update_interval": 3600,
                "batch_size": 20
            }
            logger.warning("使用默认数据收集配置")
            return default_config

    def check_okx_api_connectivity(self) -> bool:
        """检查OKX API连通性"""
        try:
            # 尝试获取健康检查端点
            response = self.session.get(f"{self.okx_api_url}/health", timeout=5)
            if response.status_code == 200:
                logger.info("OKX API连通性检查成功")
                return True
            else:
                logger.warning(f"OKX API返回状态码: {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            logger.error(f"OKX API连通性检查失败: {e}")
            return False

    def get_integration_status(self) -> Dict:
        """获取完整的集成状态"""
        status = {
            "okx_api_connected": False,
            "binance_config_available": False,
            "qlib_config_available": False,
            "symbol_mapping_available": False,
            "recommended_symbols_count": 0,
            "integration_ready": False,
        }
        
        # 检查连通性
        status["okx_api_connected"] = self.check_okx_api_connectivity()
        
        if not status["okx_api_connected"]:
            logger.error("OKX API不可用，无法获取集成状态")
            return status
        
        # 检查各配置可用性
        binance_config = self.get_binance_config()
        status["binance_config_available"] = binance_config is not None
        
        qlib_config = self.get_qlib_config()
        status["qlib_config_available"] = qlib_config is not None
        
        symbol_mapping = self.get_symbol_mapping()
        status["symbol_mapping_available"] = symbol_mapping is not None
        
        recommended_symbols = self.get_recommended_symbols()
        status["recommended_symbols_count"] = len(recommended_symbols)
        
        # 判断集成是否就绪
        status["integration_ready"] = all([
            status["okx_api_connected"],
            status["binance_config_available"],
            status["qlib_config_available"],
            status["symbol_mapping_available"],
            status["recommended_symbols_count"] > 0,
        ])
        
        logger.info(f"集成状态检查完成: 就绪={status['integration_ready']}")
        return status

    def convert_symbols_for_okx(self, binance_symbols: List[str]) -> List[str]:
        """将Binance交易对符号转换为OKX格式"""
        symbol_mapping = self.get_symbol_mapping()
        if not symbol_mapping:
            logger.error("无法获取符号映射，返回原始符号")
            return binance_symbols
        
        okx_symbols = []
        for binance_symbol in binance_symbols:
            okx_symbol = symbol_mapping.get(binance_symbol)
            if okx_symbol:
                okx_symbols.append(okx_symbol)
            else:
                logger.warning(f"未找到 {binance_symbol} 的OKX映射")
        
        logger.info(f"转换了 {len(okx_symbols)}/{len(binance_symbols)} 个交易对符号")
        return okx_symbols

    def update_qlib_config(
        self, 
        enable: Optional[bool] = None,
        min_confidence: Optional[float] = None,
        watch_symbols: Optional[List[str]] = None,
        signal_weight: Optional[float] = None,
    ) -> bool:
        """更新qlib配置"""
        update_data = {}
        
        if enable is not None:
            update_data["enable"] = enable
        if min_confidence is not None:
            update_data["min_confidence"] = min_confidence
        if watch_symbols is not None:
            update_data["watch_symbols"] = watch_symbols
        if signal_weight is not None:
            update_data["signal_weight"] = signal_weight
        
        if not update_data:
            logger.warning("没有要更新的配置项")
            return True
        
        result = self._make_request("/config/qlib", method="PUT", data=update_data)
        if result:
            logger.info("qlib配置更新成功")
            return True
        else:
            logger.error("qlib配置更新失败")
            return False


def create_okx_config_client(okx_api_url: str = None) -> OKXConfigClient:
    """创建OKX配置客户端的便捷函数"""
    if okx_api_url is None:
        # 尝试多个默认地址
        default_urls = [
            "http://localhost:9090",
            "http://127.0.0.1:9090",
            "http://localhost:8090",
        ]
        
        for url in default_urls:
            client = OKXConfigClient(okx_api_url=url)
            if client.check_okx_api_connectivity():
                logger.info(f"使用OKX API地址: {url}")
                return client
        
        logger.error("无法连接到任何OKX API地址，使用默认配置")
        return OKXConfigClient(okx_api_url=default_urls[0])
    else:
        return OKXConfigClient(okx_api_url=okx_api_url)


# 使用示例
if __name__ == "__main__":
    client = create_okx_config_client()
    
    # 获取集成状态
    status = client.get_integration_status()
    print(f"集成状态: {json.dumps(status, indent=2)}")
    
    if status["integration_ready"]:
        # 获取推荐交易对
        symbols = client.get_recommended_symbols()
        print(f"推荐交易对: {symbols[:5]}...")
        
        # 获取OKX格式符号
        okx_symbols = client.convert_symbols_for_okx(symbols[:5])
        print(f"OKX格式符号: {okx_symbols}")
    else:
        print("集成未就绪，请检查OKX API服务状态")