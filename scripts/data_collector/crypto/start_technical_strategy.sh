#!/bin/bash
# 启动纯技术分析策略 (原始策略)

echo "==============================================="
echo "    启动纯技术分析策略"
echo "==============================================="
echo

# 激活虚拟环境
if [ -f "/home/ant/project/.venv/bin/activate" ]; then
    source /home/ant/project/.venv/bin/activate
    echo "✓ 虚拟环境已激活"
else
    echo "⚠ 警告: 虚拟环境未找到，使用系统Python"
fi

# 检查是否已经运行
if pgrep -f "enhanced_binance_starter.py" > /dev/null; then
    echo "⚠ 技术分析策略已经在运行"
    echo "  如需重启，请先运行: ./stop_technical_strategy.sh"
    exit 1
fi

# 设置工作目录
cd /home/ant/project/qlib/scripts/data_collector/crypto

echo "📊 启动技术分析策略..."
echo "   - HTTP端口: 8080"
echo "   - 策略类型: 纯技术指标分析"
echo "   - 监控币种: BTC, ETH, SOL, ADA, SUI"
echo

# 启动策略
nohup python enhanced_binance_starter.py > /tmp/technical_strategy.log 2>&1 &
PID=$!

echo "✅ 技术分析策略已启动 (PID: $PID)"
echo "📝 日志文件: /tmp/technical_strategy.log"
echo "📝 详细日志: /tmp/qlib_analyzer.log"
echo
echo "测试端点:"
echo "  curl --noproxy localhost http://localhost:8080/health"
echo "  curl --noproxy localhost http://localhost:8080/signals"
echo
echo "==============================================="