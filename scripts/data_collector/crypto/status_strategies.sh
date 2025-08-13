#!/bin/bash
# 查看策略运行状态

echo "==============================================="
echo "    策略运行状态"
echo "==============================================="
echo

# 检查技术分析策略
echo "📊 技术分析策略 (端口 8080):"
if pgrep -f "enhanced_binance_starter.py" > /dev/null; then
    PID=$(pgrep -f "enhanced_binance_starter.py" | head -1)
    echo "   ✅ 运行中 (PID: $PID)"
    
    # 测试健康状态
    HEALTH=$(curl -s --noproxy localhost http://localhost:8080/health 2>/dev/null)
    if [ $? -eq 0 ]; then
        echo "   📡 API响应正常"
    else
        echo "   ⚠ API无响应"
    fi
else
    echo "   ❌ 未运行"
fi
echo

# 检查ML策略
echo "🤖 ML智能策略 (端口 8090):"
if pgrep -f "ml_strategy_analyzer.py" > /dev/null; then
    PID=$(pgrep -f "ml_strategy_analyzer.py" | head -1)
    echo "   ✅ 运行中 (PID: $PID)"
    
    # 测试健康状态
    HEALTH=$(curl -s --noproxy localhost http://localhost:8090/health 2>/dev/null)
    if [ $? -eq 0 ]; then
        echo "   📡 API响应正常"
        # 解析模型数量
        MODELS=$(echo $HEALTH | grep -o '"models_loaded":[0-9]*' | cut -d: -f2)
        if [ ! -z "$MODELS" ]; then
            echo "   🧠 已加载模型: $MODELS 个"
        fi
    else
        echo "   ⚠ API无响应"
    fi
else
    echo "   ❌ 未运行"
fi
echo

# 显示最新信号
echo "📈 最新信号概览:"
echo
echo "技术分析信号:"
curl -s --noproxy localhost http://localhost:8080/signals 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if 'data' in data:
        for signal in data['data'][:3]:  # 只显示前3个
            print(f\"  {signal.get('symbol', 'N/A')}: {signal.get('recommendation', 'N/A')} (置信度: {signal.get('confidence', 0):.2f})\")
except:
    print('  无法获取信号')
" 2>/dev/null || echo "  无法获取信号"

echo
echo "ML智能信号:"
curl -s --noproxy localhost http://localhost:8090/signals 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if 'data' in data:
        count = 0
        for symbol, signal in data['data'].items():
            if count >= 3: break  # 只显示前3个
            risk = signal.get('risk_metrics', {}).get('risk_level', 'N/A')
            print(f\"  {symbol}: {signal.get('recommendation', 'N/A')} (置信度: {signal.get('confidence', 0):.2f}, 风险: {risk})\")
            count += 1
except:
    print('  无法获取信号')
" 2>/dev/null || echo "  无法获取信号"

echo
echo "==============================================="