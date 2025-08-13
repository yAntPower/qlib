#!/bin/bash
# 停止技术分析策略

echo "正在停止技术分析策略..."

# 查找并终止进程
PIDS=$(pgrep -f "enhanced_binance_starter.py")

if [ -z "$PIDS" ]; then
    echo "❌ 技术分析策略未运行"
else
    for PID in $PIDS; do
        kill $PID
        echo "✅ 已停止进程 PID: $PID"
    done
fi