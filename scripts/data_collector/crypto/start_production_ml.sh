#!/bin/bash
# 启动生产级ML策略

echo "==============================================="
echo "    启动生产级 ML 智能策略"
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
if pgrep -f "production_ml_strategy.py" > /dev/null; then
    echo "⚠ 生产级ML策略已经在运行"
    echo "  如需重启，请先运行: ./stop_production_ml.sh"
    exit 1
fi

# 设置工作目录
cd /home/ant/project/qlib/scripts/data_collector/crypto

echo "🤖 启动生产级ML策略..."
echo "   - HTTP端口: 8091"
echo "   - 数据范围: 2021年至今 (1600+天)"
echo "   - 模型类型: LightGBM + RandomForest + GradientBoost"
echo "   - 特征数量: 100+"
echo "   - 监控币种: BTC, ETH, SOL, ADA, BNB"
echo

# 启动策略
nohup python production_ml_strategy.py > /tmp/production_ml.log 2>&1 &
PID=$!

sleep 3  # 等待服务启动

echo "✅ 生产级ML策略已启动 (PID: $PID)"
echo "📝 日志文件: /tmp/production_ml.log"
echo "📝 详细日志: /tmp/production_ml_strategy.log"
echo "💾 模型目录: ~/.qlib/production_ml_models/"
echo
echo "测试端点:"
echo "  curl --noproxy localhost http://localhost:8091/health"
echo "  curl --noproxy localhost http://localhost:8091/signals"
echo "  curl --noproxy localhost http://localhost:8091/metrics"
echo "  curl --noproxy localhost http://localhost:8091/retrain"
echo
echo "==============================================="
echo
echo "💡 特性:"
echo "  - 使用2021年至今全量数据训练"
echo "  - 100+技术指标特征"
echo "  - 特征选择和优化"
echo "  - 动态阈值调整"
echo "  - 集成多个模型"
echo "  - 包含回测系统"