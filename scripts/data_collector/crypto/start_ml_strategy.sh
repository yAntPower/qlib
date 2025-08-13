#!/bin/bash
# 启动ML/AI智能策略

echo "==============================================="
echo "    启动 AI/ML 智能分析策略"
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
if pgrep -f "ml_strategy_analyzer.py" > /dev/null; then
    echo "⚠ ML策略已经在运行"
    echo "  如需重启，请先运行: ./stop_ml_strategy.sh"
    exit 1
fi

# 检查依赖
echo "🔍 检查ML依赖..."
python -c "import sklearn, joblib" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "❌ 缺少ML依赖，正在安装..."
    pip install scikit-learn joblib
fi

# 设置工作目录
cd /home/ant/project/qlib/scripts/data_collector/crypto

echo "🤖 启动ML智能策略..."
echo "   - HTTP端口: 8090"
echo "   - 策略类型: AI/机器学习预测"
echo "   - 模型类型: RandomForest + 可选LSTM"
echo "   - 监控币种: BTC, ETH, SOL, ADA, SUI"
echo

# 启动策略
nohup python ml_strategy_analyzer.py > /tmp/ml_strategy.log 2>&1 &
PID=$!

sleep 2  # 等待服务启动

echo "✅ ML智能策略已启动 (PID: $PID)"
echo "📝 日志文件: /tmp/ml_strategy.log"
echo "📝 详细日志: /tmp/ml_strategy.log"
echo "💾 模型目录: ~/.qlib/ml_models/"
echo
echo "测试端点:"
echo "  curl --noproxy localhost http://localhost:8090/health"
echo "  curl --noproxy localhost http://localhost:8090/signals"
echo "  curl --noproxy localhost http://localhost:8090/retrain  # 重新训练模型"
echo
echo "==============================================="
echo
echo "💡 提示: ML模型会在启动时自动训练或加载已有模型"
echo "        首次训练需要一些时间，请耐心等待"